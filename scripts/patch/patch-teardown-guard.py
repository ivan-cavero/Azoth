#!/usr/bin/env python3
"""Skip the streaming-manager teardown that kills the freshly loaded world.

Measured live 2026-09-26 with Frida (`reverse/probes/client/frida-predicate-probe.py`), first
world attempt of a fresh process. The archived diagnosis in STATUS.md blamed the
virtual predicate `[*(pGame+0x60)+0x28]->vtable[0x88]`; that is WRONG:

    init-enter {'predicateArg': 0}      <- the predicate returns 0
    cleanup-enter {'frames': ['0x5a951c1', '0x644bafa', '0x1038fee', '0x646cfdd']}

`LoadContextAndLevel` (0x146448CD0) therefore never takes `jne 0x1464490e1`
(0x146448F72). The real `[ClientContext] Cleanup()` comes from the chain

    0x14646c720 -> 0x141038fe0 -> 0x14644b980 -> 0x145a95160

where 0x141038fe0 is the `streamingGDEManager` shutdown (the log line
`[streamingGDEManager] Shutting down and releasing regions`) and 0x14644b980
decides with a single guard:

    14644bad7  mov rcx, qword ptr [rsi + 0x1e0]   ; list begin
    14644bade  cmp rcx, qword ptr [rsi + 0x1e8]   ; list end
    14644bae5  je  0x14644bbd1                    ; EMPTY -> skip the teardown
    14644baeb  mov rcx, qword ptr [rcx]           ; first element
    14644baee  add rcx, 0x130                     ; its ClientContext
    14644baf5  call 0x145a95160                   ; ctx->failed = 1; Cleanup()

and 0x145a95160 does exactly the pair seen in Game.log:

    145a951a8  mov byte ptr [rbx + 0x1a2], 1
    145a951bc  call 0x146455e90                   ; ClientContext::Cleanup

The list is NOT empty during the world attempt, so the teardown runs and the
context that was just initialized dies in the same millisecond. Every later
state bundle is then dropped with
`HandleUnexpectedMessage skipping ReceiveStateBundle ... clientContext == nullptr`,
so the local player actor never appears: black screen, then
`connection_player_timeout` at ~120 s.

This patch turns the `je` into an unconditional `jmp` to the same target, so the
teardown is skipped for every element of that list. In-memory only, private
runtime only (no EAC) — see research/docs/EAC.md for the scoped ban. Restore by
restarting the game; nothing is written to disk.

Usage: python scripts/patch-teardown-guard.py
"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE_BASE = 0x140000000

# 14644bae5  je 0x14644bbd1 (rel32 0xe6)  ->  jmp 0x14644bbd1 ; nop
VA = 0x14644BAE5
ORIG = bytes.fromhex("0f84e6000000")
WANT = bytes.fromhex("e9e700000090")

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


def patch(pid: int) -> bool:
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
        print(f"[teardown-guard] module base {base_addr:#x}")

        addr = ctypes.c_void_p(base_addr + (VA - IMAGE_BASE))
        cur = ctypes.create_string_buffer(len(ORIG))
        read = ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, addr, cur, len(ORIG), ctypes.byref(read)):
            print(f"[teardown-guard] {VA:x} read failed: {ctypes.GetLastError()}")
            return False
        if cur.raw == WANT:
            print(f"[teardown-guard] {VA:x} already patched")
            return True
        if cur.raw != ORIG:
            print(f"[teardown-guard] {VA:x} unexpected bytes {cur.raw.hex()}")
            return False
        old = ctypes.c_ulong()
        if not k32.VirtualProtectEx(
            h, addr, len(WANT), PAGE_READWRITE, ctypes.byref(old)
        ):
            print(f"[teardown-guard] VirtualProtectEx failed: {ctypes.GetLastError()}")
            return False
        written = ctypes.c_size_t()
        done = bool(k32.WriteProcessMemory(h, addr, WANT, len(WANT), ctypes.byref(written)))
        k32.VirtualProtectEx(h, addr, len(WANT), old.value, ctypes.byref(old))
        print(
            f"[teardown-guard] {VA:x} "
            f"{'patched' if done else 'WRITE FAILED'}: {ORIG.hex()} -> {WANT.hex()}"
        )
        return done
    finally:
        k32.CloseHandle(h)


def main() -> int:
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
        if patch(pid.value):
            return 0
        time.sleep(2)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
