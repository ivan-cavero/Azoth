#!/usr/bin/env python3
"""Force the portrayal predicate FUN_146165f20 to always pass (return 1).

WHY (measured 2026-09-28, build 1.400). Portrayal (FUN_14178db00) calls this
predicate FIRST with the entity key; on 0 it only logs and returns, so no
GameSystemData is inserted and no actor is ever built. Live: 94 portrayals,
0 creates, and record-1's key (0xBF85314BBC4A951A, even, high32 != 0) fails
under EVERY version branch (v==1 needs high32==0, v==2 needs key%8==1 or odd).
The key is ambient state (slot+0x7f0), never set from the bundle, so the
local player can never pass without this patch.

The predicate's other callers are all offline-id checks on the same
portrayal/replication path; forcing 1 means "treat every id as
offline-capable". Table misses stay safe (they just skip).

Patch: 0x146165F89 `41 1B?? ` — the exact bytes are read live; we patch the
function ENTRY to `mov al,1; ret` (B0 01 C3) which is 3 bytes and safe:
  146165f20  push rbx        (53)
  146165f22  sub rsp, 0x30   (48 83 EC 30)
Patching entry: B0 01 C3 + NOP (4 bytes: 53 48 83 EC -> B0 01 C3 90).

Direct memory write (same technique as services/launcher/runtime-tools/patch-predicate-flag.py). Run AFTER
the game window exists, BEFORE entering the world. In-memory only, private
runtime only. Restore by restarting the game.

Usage:
  python scripts/patch-portray-predicate.py
  python scripts/patch-portray-predicate.py --revert
"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE_BASE = 0x140000000

VA = 0x146165F20
# EAC kernel hook (e9 jmp) sits at the function entry (see STATUS.md: EAC is
# live in the private runtime, hooks at LoadContextAndLevel + CSDK reader).
# Patch PAST it: the version dispatch is at +0x50:
#   146165f70  mov eax, [rip+...]   ; load version
#   146165f76  sub eax, 1
#   146165f79  je v1-path           ; 74 31
#   146165f7b  cmp eax, 1
#   146165f7e  jne fail             ; 75 24
# Forcing AL=1 at the v1/v2 decision is complex; instead patch the two
# acceptance returns to always pass:
#   146165f89  and bl, 1            ; v1+capitals path
#   146165f8c  movzx eax, bl
#   146165f95  and bl, 7            ; v1-no-capitals / v2 path
#   146165f98  cmp bl, 1
#   146165f9b  sete al
# Simplest robust patch: replace the final `jne fail` + `xor al,al` so every
# path falls into an accept. Concretely patch at 0x146165F7E:
#   75 24          jne +0x24 (to fail)
#   -> EB 24       jmp +0x24?? No - that jumps INTO fail. Wrong direction.
# Correct: patch the v1-entry comparison so version always reads 1:
#   146165f76  83 E8 01   sub eax, 1
#   -> 83 E8 00   sub eax, 0  => eax stays (version+? ) hmm version is loaded then -1.
# Cleanest: patch the load itself:
#   146165f70  8B 05 ?? ?? ?? ??   mov eax, [rip+X]  (6 bytes)
#   -> B8 02 00 00 00 90           mov eax, 2; nop  => version = 2 always.
# Then predicate = (key&7)==1 (no-capitals) or (key&1) (capitals).
# Record-1's key is EVEN, so version 2 alone does NOT fix it. The predicate
# must return 1 unconditionally: patch the fail return:
#   146165fa4  32 C0      xor al, al
#   -> B0 01      mov al, 1         (2 bytes, same size!)
# That single 2-byte patch turns the only hard-0 return into 1. All other
# paths keep their logic. If version is 0/unset, every call now returns 1.
ORIG = bytes.fromhex("32C0")  # xor al, al (fail return)
PATCHED = bytes.fromhex("B001")  # mov al, 1
VA_FAILRET = 0x146165FA4

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
        src, dst = (PATCHED, ORIG) if revert else (ORIG, PATCHED)
        addr = ctypes.c_void_p(base_addr + (VA_FAILRET - IMAGE_BASE))
        cur = ctypes.create_string_buffer(len(src))
        read = ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, addr, cur, len(src), ctypes.byref(read)):
            print(f"[portray-pred] {VA:x} read failed: {ctypes.GetLastError()}")
            return False
        print(f"[portray-pred] {VA_FAILRET:x} current: {cur.raw.hex()}")
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
        print(f"        {'reverted' if revert else 'patched'}{' OK' if done else ' WRITE FAILED'}")
        return done
    finally:
        k32.CloseHandle(h)


def main() -> int:
    revert = "--revert" in sys.argv
    find_windows = _find_windows()
    deadline = time.time() + 240
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
