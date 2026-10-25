#!/usr/bin/env python3
"""Force the 4th spawn gate (13->14) — direct memory write, no Frida.

Frida's Interceptor crashed the client during startup races
(c0000005 in frida-agent.dll, WER 2026-09-19 20:20). For a fixed
byte-patch we do not need Frida at all: VirtualProtectEx + WriteProcess
Memory from this stdlib script does it deterministically.

What is patched — the `case 0xd:` arm of the GameConnection state machine
(1.400 FUN_14644xxxx, 1.460 FUN_14644b330, corpus range 14644b330-14644bda4):

    1.460  14644bba0  call 0x141026220       ; singleton manager
    1.460  14644bba4  mov rdx, [rax]
    1.460  14644bba7  mov rcx, rax
    1.460  14644bba9  call qword ptr [rdx+0x30]  ; returns [mgr+8] (NULL: the
                                           ; replica stream never created
                                           ; the local player entity)
    1.460  14644bbad  test rax, rax    <- NOP x9 (test + je)
    1.460  14644bbb6  ... falls through -> FSM transitions 13->14

The getter body stays intact (600+ callers). Run AFTER the game window
exists (the watch flow calls it once the process is mapped).

HOW THE 1.460 SITE WAS RE-DERIVED (2026-10-22). `0x14644A8ED` is inside an
unrelated instruction in 1.460. The anchor is the gate's own shape,
`call [rdx+0x30]; test rax,rax; je <rel32>; lea rdx,[rip+..]`
(`bytepat.py spawn-gate-13-14`): a single hit in 1.460 .text at 0x14644BBA9,
and the patch site is 4 bytes later. The bytes of the patched instruction pair
are unchanged from 1.400 (`48 85 c0 0f 84 b6 00 00 00`). The corpus
confirmation is semantic: FUN_14644b330 switches on `[conn+0x1530]`, its
`case 0xd:` calls the player-spawn getter (0x145A934F0, the third ladder getter),
then the singleton's `[vtable+0x30]`, and only advances the state to 0xe when
that returns non-zero — which is exactly what NOPing the test/je forces.
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_sites  # noqa: E402
from build_sites import BUILD_1_400, BUILD_1_460, Site  # noqa: E402

TAG = "patch"

ORIG = bytes.fromhex("4885C00F84B6000000")  # test rax,rax; je +0xb6 (9B)
WANT = bytes.fromhex("90" * 9)  # unconditional fall-through to the transition
# v1 of this tool NOPed only `test rax,rax` and left the je intact.
PARTIAL = bytes.fromhex("9090900F84B6000000")

SITES: dict[str, tuple[Site, ...]] = {
    BUILD_1_400: (Site(0x14644A8ED, ORIG, WANT, "4th spawn gate (FSM 13->14)"),),
    BUILD_1_460: (Site(0x14644BBAD, ORIG, WANT, "4th spawn gate (FSM 13->14)"),),
}

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PAGE_READWRITE = 0x04

k32 = ctypes.windll.kernel32


def find_windows(title_sub: str) -> list[tuple[int, str]]:
    """Same enumeration as send-input.py (import sibling by path)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "send_input", HERE.parents[2] / "scripts" / "gui" / "send-input.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_windows(title_sub)


def patch(pid: int, sites: tuple[Site, ...]) -> bool:
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, pid)
    if not h:
        print(f"OpenProcess({pid}) failed: {ctypes.GetLastError()}")
        return False
    try:
        # Modules are ASLR-mapped; find the actual base of NewWorld.exe.
        psapi = ctypes.windll.psapi
        hmods = (ctypes.c_void_p * 1024)()
        needed = ctypes.c_ulong()
        if not psapi.EnumProcessModulesEx(h, hmods, ctypes.sizeof(hmods), ctypes.byref(needed), 3):
            print("EnumProcessModulesEx failed")
            return False
        base_addr = int(hmods[0])  # c_void_p auto-converts to int in the array
        name = ctypes.create_unicode_buffer(260)
        hmod0 = ctypes.c_void_p(int(hmods[0]))
        psapi.GetModuleFileNameExW(h, hmod0, name, 260)
        print(f"[{TAG}] module base {base_addr:#x}: {name.value}")
        if "NewWorld.exe" not in name.value:
            print(f"module 0 is not NewWorld.exe: {name.value}")
            return False

        ok_all = True
        for site in sites:
            addr = ctypes.c_void_p(base_addr + (site.va - build_sites.IMAGE_BASE))
            # Context dump: the call opcode at SITE-0x10 must be E8 (the
            # manager virtual); padding/mismatch means a moved site.
            ctx = ctypes.create_string_buffer(0x20)
            r = ctypes.c_size_t()
            k32.ReadProcessMemory(h, ctypes.c_void_p(addr.value - 0x10), ctx, 0x20, ctypes.byref(r))
            print(f"[{TAG}] ctx from {site.va - 0x10:#x}: {ctx.raw[: r.value].hex()}")
            cur = ctypes.create_string_buffer(len(site.orig))
            read = ctypes.c_size_t()
            k32.ReadProcessMemory(h, addr, cur, len(site.orig), ctypes.byref(read))
            current = cur.raw[: len(site.orig)]
            print(
                f"[{TAG}] {site.va:#x} ({site.label}) current: {current.hex()}"
                f" (expected {site.orig.hex()})"
            )
            if current == site.want:
                print("        already patched")
                continue
            if current != site.orig and current != PARTIAL:
                print(f"        mismatch: {current.hex()} (expected {site.orig.hex()})")
                ok_all = False
                continue
            old = ctypes.c_ulong()
            if not k32.VirtualProtectEx(h, addr, len(site.want), PAGE_READWRITE, ctypes.byref(old)):
                print(f"        VirtualProtectEx failed: {ctypes.GetLastError()}")
                ok_all = False
                continue
            written = ctypes.c_size_t()
            done = bool(
                k32.WriteProcessMemory(h, addr, site.want, len(site.want), ctypes.byref(written))
            )
            k32.VirtualProtectEx(h, addr, len(site.want), old.value, ctypes.byref(old))
            if done:
                print(f"        patched {site.va:#x}: {current.hex()} -> {site.want.hex()}")
            else:
                print(f"        WriteProcessMemory failed: {ctypes.GetLastError()}")
            ok_all = ok_all and done
        return ok_all
    finally:
        k32.CloseHandle(h)


def main() -> int:
    if "--check" in sys.argv:
        return build_sites.report_check(SITES, TAG)

    build, _exe, note = build_sites.identify(SITES)
    sites = SITES[build]
    print(f"[{TAG}] build sha256={build}")
    print(f"[{TAG}] {note}")
    for site in sites:
        print(f"[{TAG}] {site.detail()}")

    wins = find_windows("New World")
    if not wins:
        print("New World window not found")
        return 1
    hwnd = wins[0][0]
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    for _ in range(10):  # the game takes a moment to map .text
        if patch(pid.value, sites):
            return 0
        time.sleep(2)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
