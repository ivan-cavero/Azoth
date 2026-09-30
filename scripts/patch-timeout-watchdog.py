#!/usr/bin/env python3
"""Stop the client's InGame state watchdog from tearing the world down.

WHY. Once the replay stream ends, the client sits in the `InGame` state and a
per-state watchdog (FUN_146445E10) counts intervals in which the message the
state expects did not arrive. Measured live 2026-09-27 with a Frida probe on
that function:

    call  state  f18  f1c
     364     14    1    1     <- f18 reached its limit ([descriptor+0x10])
     365     14    1    2
     ...
     373     14    1   10
     374      0    0    0     <- f1c hit 10 -> timeout -> Disconnected

and Game.log reports it as

    [GameConnection] State(InGame) is timeout : frames 10, currentTimeoutIntervalCount 1
    [ERROR] GameConnection: Report Error: Reason: Errors::connection_ingame_timeout
    [ERROR] Game: JavelinGame::OnConnectionFail: Reason: Errors::connection_ingame_timeout

The disconnect is retryable (`shouldRetryConnect=true`), so the client
re-enters the world every time — but it drops out every ~58 s, which makes the
world unplayable.

The reporting site is a single two-byte instruction:

    146445ef5  xor eax, eax
    146445ef7  mov qword ptr [rbx + 0x18], rax   ; reset both counters
    146445efb  mov al, 1                         ; <- return TRUE = timed out
    146445efd  mov rbx, qword ptr [rsp + 0x58]
    ...
    146445f0a  inc eax                           ; the other path: f1c++

Patching `mov al, 1` to `mov al, 0` keeps the bookkeeping (the counters still
reset) but never reports a timeout, so the state machine no longer forces a
disconnect. This is the same class of in-memory, private-runtime patch as
`patch-predicate-flag.py`; it is a sandbox affordance, not a protocol fix —
the proper fix is to keep sending the messages the InGame state expects, which
is what `rep.py`'s post-replay heartbeat (`AZOTH_REPLAY_HEARTBEAT`) starts
doing (it already stretched the window from ~44 s to ~58 s).

Restore by restarting the game. In-memory only, private runtime only (no EAC)
— see research/docs/EAC.md for the scoped ban.

Usage:
  python scripts/patch-timeout-watchdog.py
  python scripts/patch-timeout-watchdog.py --revert
  python scripts/patch-timeout-watchdog.py --timeout 240
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
        0x146445EFB,
        bytes.fromhex("B001"),  # mov al, 1  -> "timed out"
        bytes.fromhex("B000"),  # mov al, 0  -> never report a timeout
        "InGame watchdog return value",
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
        print(f"[timeout-watchdog] module base {base_addr:#x}")

        ok_all = True
        for va, orig, want, label in PATCHES:
            src, dst = (want, orig) if revert else (orig, want)
            addr = ctypes.c_void_p(base_addr + (va - IMAGE_BASE))
            cur = ctypes.create_string_buffer(len(src))
            read = ctypes.c_size_t()
            if not k32.ReadProcessMemory(h, addr, cur, len(src), ctypes.byref(read)):
                print(f"[timeout-watchdog] {va:x} read failed: {ctypes.GetLastError()}")
                ok_all = False
                continue
            print(f"[timeout-watchdog] {va:x} ({label}) current: {cur.raw.hex()}")
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