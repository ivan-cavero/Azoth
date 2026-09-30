#!/usr/bin/env python3
"""Let the local-player actor build: skip the "count >= 3" guard.

WHY. The record handler FUN_141717fc0 builds the local-player actor only for
records whose parsed `interestId` ([rbp+0x268], visitor registered at
0x14171800c) is 1, and only after four guards. Measured live 2026-09-27 with
scripts/frida-actor-guards.py + scripts/frida-guard-value.py:

    interest_is_1 : 25     interestId == 1 passed 25 times
    slot_true     : 25     [r13+0x850]->vtable[0x20]() returned true
    guard3_pass   : 25     [[r12]] == 0 passed
    prop_call     : 25     call 0x146165ff0(obj, 3) reached
    actor_build   :  0     <-- the actor build is NEVER entered
    guard value   : [obj+0x18] = 2, id = 3   (25/25)

and the callee is a one-liner:

    146165ff0  cmp dword ptr [rcx + 0x18], edx
    146165ff3  setae al                 ; al = ([obj+0x18] >= id)
    146165ff6  ret

so the guard fails because the local-player record carries 2 where 3 is
required. Without the actor there is no camera, the world renders black, and
the player cannot move.

This patch NOPs the branch that consumes that result at the call site, so the
actor build runs for every interestId == 1 record:

    1417182ce  call 0x146165ff0(obj, 3)
    1417182d5  je 0x14171836d           ; 0F 84 92 00 00 00 -> 6x NOP

It is deliberately narrow: the shared helper 0x146165ff0 has 4654 callers and
is left untouched.

RESULT (2026-09-27): forcing this branch does NOT build the actor. With the
patch applied the entity table still ends up with 14 nodes, 13 carrying vtable
`nw+8033f90` and the local player (id 13) still carrying the corrupt
`nw+ffff800964c60001`, and the world still renders black. So the record is
genuinely missing whatever the third element is; the guard is telling the
truth. Kept as evidence and as a lever to re-test once the record's content is
understood — do not treat it as a fix.

In-memory only, private runtime only (no EAC). Restore with --revert or by
restarting the game.
"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE_BASE = 0x140000000

# 1417182d5  je 0x14171836d (rel32 0x92)  ->  6x NOP
VA = 0x1417182D5
ORIG = bytes.fromhex("0f8492000000")
WANT = bytes.fromhex("90" * 6)

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PAGE_READWRITE = 0x04

k32 = ctypes.windll.kernel32


def _find_windows():
    spec = importlib.util.spec_from_file_location("si", HERE / "send-input.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_windows


def patch(pid: int, revert: bool = False) -> bool:
    h = k32.OpenProcess(
        PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, pid
    )
    if not h:
        print(f"OpenProcess({pid}) failed: {ctypes.GetLastError()}")
        return False
    try:
        psapi = ctypes.windll.psapi
        hmods = (ctypes.c_void_p * 1024)()
        needed = ctypes.c_ulong()
        if not psapi.EnumProcessModulesEx(
            h, hmods, ctypes.sizeof(hmods), ctypes.byref(needed), 3
        ):
            print("EnumProcessModulesEx failed")
            return False
        base_addr = int(hmods[0])
        name = ctypes.create_unicode_buffer(260)
        psapi.GetModuleFileNameExW(h, ctypes.c_void_p(base_addr), name, 260)
        if "NewWorld.exe" not in name.value:
            print(f"module 0 is not NewWorld.exe: {name.value}")
            return False
        print(f"[actor-guard] module base {base_addr:#x}")

        src, dst = (WANT, ORIG) if revert else (ORIG, WANT)
        addr = ctypes.c_void_p(base_addr + (VA - IMAGE_BASE))
        cur = ctypes.create_string_buffer(len(src))
        read = ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, addr, cur, len(src), ctypes.byref(read)):
            print(f"[actor-guard] {VA:x} read failed: {ctypes.GetLastError()}")
            return False
        print(f"[actor-guard] {VA:x} current: {cur.raw.hex()}")
        if cur.raw == dst:
            print("        already in the requested state")
            return True
        if cur.raw != src:
            print(f"        unexpected bytes (wanted {src.hex()})")
            return False
        old = ctypes.c_ulong()
        if not k32.VirtualProtectEx(h, addr, len(dst), PAGE_READWRITE, ctypes.byref(old)):
            print(f"        VirtualProtectEx failed: {ctypes.GetLastError()}")
            return False
        written = ctypes.c_size_t()
        done = bool(k32.WriteProcessMemory(h, addr, dst, len(dst), ctypes.byref(written)))
        k32.VirtualProtectEx(h, addr, len(dst), old.value, ctypes.byref(old))
        print(
            f"        {'reverted' if revert else 'patched'}"
            f"{' OK' if done else ' WRITE FAILED'}: {src.hex()} -> {dst.hex()}"
        )
        return done
    finally:
        k32.CloseHandle(h)


def main() -> int:
    revert = "--revert" in sys.argv
    timeout = 240
    if "--timeout" in sys.argv:
        timeout = int(sys.argv[sys.argv.index("--timeout") + 1])
    find_windows = _find_windows()

    deadline = time.time() + timeout
    wins: list = []
    while time.time() < deadline:
        try:
            wins = find_windows("New World")
        except Exception:
            wins = []
        if wins:
            break
        time.sleep(2)
    if not wins:
        print("TIMEOUT: New World window never appeared")
        return 1

    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(wins[0][0], ctypes.byref(pid))
    for _ in range(10):
        if patch(pid.value, revert=revert):
            return 0
        time.sleep(2)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())