#!/usr/bin/env python3
"""Give ClientContext::Initialize the "ok" flag it needs to not self-clean.

WHY (measured, not guessed). LoadContextAndLevel (0x146448CD0) reads a virtual
predicate three times and feeds the FIRST result to Initialize as its 7th
argument:

    146448e8c  call qword ptr [rdx + 0x88]   ; predicate  (receiver = pGame+0x28)
    146448e92  movzx ebx, al                 ; ebx = result1
    ...
    146448eca  mov byte ptr [rsp + 0x30], bl ; -> 7th arg of Initialize
    146448ee8  call 0x14171B850              ; ClientContext::Initialize

Inside Initialize the flag is the ONLY thing between the "Initialize()" log and
the "Cleanup()" log:

    14171ba1e  lea rdx, "Initialize()"
    14171ba2c  call log
    14171ba31  cmp byte ptr [rsp + 0x110], 0   ; == the caller's [rsp+0x30]
    14171ba39  jne 0x14171ba43                 ; NON-ZERO -> skip
    14171ba3b  mov rcx, rdi                    ; rdi = the context argument
    14171ba3e  call 0x1416835B0                ; logs "Cleanup()" on the SAME ctx

Measured live with Frida (scripts/frida-predicate-probe.py, first world attempt
of a fresh process): the predicate returns 0. So Initialize takes the cleanup
branch on the context it was just handed, and every later state bundle is
dropped with `clientContext == nullptr` — black screen, no local player actor,
`connection_player_timeout` at ~120 s.

THE ARCHIVED PATCH IS INVERTED. scripts/patch-context-gate.py writes
`31 DB 90` (xor ebx, ebx) at 0x146448E92, i.e. it FORCES the flag to 0 — the
exact value that triggers the self-cleanup. That is why "forcing the predicate
did not stop the cleanup" (its own header admits it): it was forcing the wrong
value.

The second predicate call must ALSO be neutralised, because the same getter on
the same object is read again right after Initialize and a non-zero there takes
the failure branch:

    146448f67  call qword ptr [rax + 0x88]   ; predicate again
    146448f70  test al, al
    146448f72  jne 0x1464490e1               ; non-zero -> [ctx+0x1a2]=1; Cleanup

So both sites are patched:

  1. 0x146448E92  `0F B6 D8` (movzx ebx, al) -> `B3 01 90` (mov bl, 1 ; nop)
     Initialize receives "ok" and initialises instead of cleaning up.
  2. 0x146448F72  `0F 85 69 01 00 00` (jne 0x1464490e1) -> six NOPs
     the failure branch can never be taken.

Direct memory write (no Frida: its Interceptor raced during startup). Run AFTER
the game window exists. In-memory only, private runtime only (no EAC) — see
research/docs/EAC.md for the scoped ban. Restore by restarting the game.

Usage:
  python scripts/patch-predicate-flag.py            # apply (flag=1 + nofail)
  python scripts/patch-predicate-flag.py --revert   # put the original bytes back
  python scripts/patch-predicate-flag.py --timeout 240
"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE_BASE = 0x140000000

# (va, original, patched, label)
PATCHES = (
    (
        0x146448E92,
        bytes.fromhex("0FB6D8"),  # movzx ebx, al
        bytes.fromhex("B30190"),  # mov bl, 1 ; nop  -> Initialize gets "ok"
        "predicate flag handed to clientContext->Initialize (0 -> 1)",
    ),
    (
        0x146448F72,
        bytes.fromhex("0F8569010000"),  # jne 0x1464490e1 (rel32 0x169)
        bytes.fromhex("90" * 6),  # never take the failure branch
        "jne to the Cleanup failure branch",
    ),
)

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
        print(f"[predicate-flag] module base {base_addr:#x}")

        ok_all = True
        for va, orig, want, label in PATCHES:
            src, dst = (want, orig) if revert else (orig, want)
            addr = ctypes.c_void_p(base_addr + (va - IMAGE_BASE))
            cur = ctypes.create_string_buffer(len(src))
            read = ctypes.c_size_t()
            if not k32.ReadProcessMemory(h, addr, cur, len(src), ctypes.byref(read)):
                print(f"[predicate-flag] {va:x} read failed: {ctypes.GetLastError()}")
                ok_all = False
                continue
            print(f"[predicate-flag] {va:x} ({label}) current: {cur.raw.hex()}")
            if cur.raw == dst:
                print("        already in the requested state")
                continue
            if cur.raw != src:
                print(f"        unexpected bytes (wanted {src.hex()})")
                ok_all = False
                continue
            old = ctypes.c_ulong()
            if not k32.VirtualProtectEx(
                h, addr, len(dst), PAGE_READWRITE, ctypes.byref(old)
            ):
                print(f"        VirtualProtectEx failed: {ctypes.GetLastError()}")
                ok_all = False
                continue
            written = ctypes.c_size_t()
            done = bool(
                k32.WriteProcessMemory(h, addr, dst, len(dst), ctypes.byref(written))
            )
            k32.VirtualProtectEx(h, addr, len(dst), old.value, ctypes.byref(old))
            print(
                f"        {'reverted' if revert else 'patched'}"
                f"{' OK' if done else ' WRITE FAILED'}: {src.hex()} -> {dst.hex()}"
            )
            ok_all = ok_all and done
        return ok_all
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
