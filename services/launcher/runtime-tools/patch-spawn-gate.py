#!/usr/bin/env python3
"""Force the 4th spawn gate (13->14) — direct memory write, no Frida.

Frida's Interceptor crashed the client during startup races
(c0000005 in frida-agent.dll, WER 2026-09-19 20:20). For a fixed
byte-patch we do not need Frida at all: VirtualProtectEx + WriteProcess
Memory from this stdlib script does it deterministically.

What is patched (see disasm 0x14644a8bd..0x14644a8f0):
    14644a8d1  call 0x141026080           ; singleton manager
    14644a8df  call qword ptr [rdx+0x30]  ; returns [mgr+8] (NULL: the
                                           ; replica stream never created
                                           ; the local player entity)
    14644a8ed  test rax, rax    <- NOP x3
    14644a8f0  je 0x14644a9ac   ; falls through -> FSM transitions 13->14

The getter body stays intact (600+ callers). Run AFTER the game window
exists (the watch flow calls it once the process is mapped).
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))


def find_windows(title_sub: str) -> list[tuple[int, str]]:
    """Same enumeration as send-input.py (import sibling by path)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "send_input", Path(__file__).resolve().parents[3] / "scripts" / "send-input.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_windows(title_sub)

IMAGE_BASE = 0x140000000
SITE = 0x14644A8ED
ORIG = bytes.fromhex("4885C00F84B6000000")  # test rax,rax; je +0xb6 (6B)
WANT = bytes.fromhex("90" * 9)  # unconditional fall-through to transition

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PAGE_READWRITE = 0x04

k32 = ctypes.windll.kernel32


def patch(pid: int) -> bool:
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, pid)
    if not h:
        print(f"OpenProcess({pid}) failed: {ctypes.GetLastError()}")
        return False
    try:
        base = ctypes.c_void_p(IMAGE_BASE)
        buf = ctypes.c_void_p()
        # Modules are ASLR-mapped; find the actual base of NewWorld.exe.
        psapi = ctypes.windll.psapi
        hmods = (ctypes.c_void_p * 1024)()
        needed = ctypes.c_ulong()
        if not psapi.EnumProcessModulesEx(h, hmods, ctypes.sizeof(hmods), ctypes.byref(needed), 3):
            print("EnumProcessModulesEx failed")
            return False
        base_addr = int(hmods[0])  # c_void_p auto-converts to int in the array
        # Verify hmods[0] is really the EXE: the call opcode at SITE-0x1C
        # (14644a8d1) must be E8. Padding/padding-mismatch means wrong module.
        name = ctypes.create_unicode_buffer(260)
        hmod0 = ctypes.c_void_p(int(hmods[0]))
        psapi.GetModuleFileNameExW(h, hmod0, name, 260)
        print(f"[patch] module base {base_addr:#x}: {name.value}")
        addr = ctypes.c_void_p(base_addr + (SITE - IMAGE_BASE))
        ctx = ctypes.create_string_buffer(0x20)
        r = ctypes.c_size_t()
        k32.ReadProcessMemory(h, ctypes.c_void_p(addr.value - 0x1C), ctx, 0x20, ctypes.byref(r))
        print(f"[patch] ctx from SITE-0x1C: {ctx.raw[:r.value].hex()}")
        old = ctypes.c_ulong()
        if not k32.VirtualProtectEx(h, addr, len(WANT), PAGE_READWRITE, ctypes.byref(old)):
            print(f"VirtualProtectEx failed: {ctypes.GetLastError()}")
            return False
        cur = ctypes.create_string_buffer(len(ORIG))
        read = ctypes.c_size_t()
        k32.ReadProcessMemory(h, addr, cur, len(ORIG), ctypes.byref(read))
        print(f"[patch] {SITE:x} current bytes: {cur.raw.hex()}")
        if cur.raw == WANT:
            print("already patched")
            k32.VirtualProtectEx(h, addr, len(WANT), old.value, ctypes.byref(old))
            return True
        # Accept the v1 partial patch (test NOPed, je intact) as a valid base.
        partial = bytes.fromhex("9090900F84B6000000".lower())
        if cur.raw != ORIG and cur.raw != partial:
            print(f"mismatch: {cur.raw.hex()} (expected {ORIG.hex()})")
            k32.VirtualProtectEx(h, addr, len(WANT), old.value, ctypes.byref(old))
            return False
        written = ctypes.c_size_t()
        ok = bool(k32.WriteProcessMemory(h, addr, WANT, len(WANT), ctypes.byref(written)))
        k32.VirtualProtectEx(h, addr, len(WANT), old.value, ctypes.byref(old))
        if ok:
            print(f"patched {SITE:x}: {ORIG.hex()} -> {WANT.hex()}")
        else:
            print(f"WriteProcessMemory failed: {ctypes.GetLastError()}")
        return ok
    finally:
        k32.CloseHandle(h)


def main() -> int:
    wins = find_windows("New World")
    if not wins:
        print("New World window not found")
        return 1
    hwnd = wins[0][0]
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    for _ in range(10):  # the game takes a moment to map .text
        if patch(pid.value):
            return 0
        time.sleep(2)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
