#!/usr/bin/env python3
"""Stop the client's 20-minute "exit to main menu" delegate from leaving the world.

WHY. Measured live 2026-10-11: a clean session reaches `player spawn succeeds` and
then, at **20 min 0.4 s** exactly, logs

    [Game] CGame exiting to main menu
    [ClientContext] Cleanup()

with `transportError` 0 and `ActorContainerDisconnect` 0 — a clean logout, not a
network failure. It is armed at the spawn transition and fires on a tenth of a
second, so it is a deadline, not a watchdog.

The prior patch (`reverse/probes/client/frida-patch-exit-once.py`) NOPed
`0x141004230` and **did not stop the exit**. The static pass
(`.azoth/night/subagent-20min-exit-real-path.md`) explains why: `0x141004230` is
one statement inside the teardown delegate `FUN_141004100`, not the teardown.
After it, the same call continues to the statement that actually leaves the
world:

    141004230  e8 ...            call CGame::ActorContainerDisconnect   <- old patch
    14100425F  ff 90 d8 01 00 00 call qword ptr [rax + 0x1d8]          <- the real exit
                                     -> FUN_141037b20 (logs "exiting to main menu"
                                        and calls ClientContext Cleanup())

NOPing `0x141004230` therefore removed only the `ActorContainerDisconnect` log
line; the delegate fell straight through to the exit virtual — exactly the
refuting Game.log (`ActorContainerDisconnect` 0, `exiting to main menu` 1,
`Cleanup()` 1, same 20:00.4 timing).

This patch NOPs the six bytes of the exit virtual call. The preceding
disconnect notification and the `conn+0x730` free still happen (harmless).

This is the same class of in-memory, private-runtime sandbox affordance as
`patch-timeout-watchdog.py`, not a protocol fix: the proper fix is to satisfy
whatever the server is supposed to send to keep the session alive. Restore by
restarting the game. Private runtime only (no EAC).

Usage:
  python services/launcher/runtime-tools/patch-exit-to-menu.py
  python services/launcher/runtime-tools/patch-exit-to-menu.py --revert
  python services/launcher/runtime-tools/patch-exit-to-menu.py --timeout 240
"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE_BASE = 0x140000000

# (va, original, patched, label) — per build, keyed by the executable SHA-256.
#
# The call bytes are identical between builds; only the address moves.
# 1.400.6031.6004151 / 8654f01d...: 0x14100425F
# 1.460.6033.6024067 / 30fe6461...: 0x1410043FF   (delta +0x1A0)
#
# `ff 90 d8 01 00 00` alone occurs 156 times in the 1.460 image, so the address
# was pinned by CONTEXT, and both neighbours are unique in the whole image:
#   before: 48 8b 01 33 d2   mov rax,[rcx] ; xor edx,edx      (1 occurrence)
#   after : 83 3b 02         cmp dword ptr [rbx],2            (1 occurrence)
PATCH_SITES = {
    "8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e": 0x14100425F,
    "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033": 0x1410043FF,
}
DEFAULT_SITE = 0x1410043FF

def resolve_site() -> int:
    """The virtual-call address for this build, by the OFFICIAL exe's hash.

    The private copy's hash changes once it carries the on-disk DTLS patch, so the
    Steam executable is the stable identity.
    """
    import hashlib
    import os

    install = os.environ.get("AZOTH_GAME_INSTALL") or r"C:\Program Files (x86)\Steam\steamapps\common\New World"
    official = Path(install) / "Bin64" / "NewWorld.exe"
    try:
        digest = hashlib.sha256(official.read_bytes()).hexdigest()
    except OSError:
        digest = ""
    return PATCH_SITES.get(digest, DEFAULT_SITE)

PATCHES = (
    (
        resolve_site(),
        bytes.fromhex("FF90D8010000"),  # call qword ptr [rax+0x1d8]
        bytes.fromhex("909090909090"),  # NOP x6
        "delegate exit-to-main-menu virtual call",
    ),
)

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PAGE_READWRITE = 0x04

k32 = ctypes.windll.kernel32


def _find_windows():
    input_helper = HERE.parents[2] / "scripts" / "gui" / "send-input.py"
    spec = importlib.util.spec_from_file_location("si", input_helper)
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
        print(f"[exit-to-menu] module base {base_addr:#x}")

        ok_all = True
        for va, orig, want, label in PATCHES:
            src, dst = (want, orig) if revert else (orig, want)
            addr = ctypes.c_void_p(base_addr + (va - IMAGE_BASE))
            cur = ctypes.create_string_buffer(len(src))
            read = ctypes.c_size_t()
            if not k32.ReadProcessMemory(h, addr, cur, len(src), ctypes.byref(read)):
                print(f"[exit-to-menu] {va:x} read failed: {ctypes.GetLastError()}")
                ok_all = False
                continue
            print(f"[exit-to-menu] {va:x} ({label}) current: {cur.raw.hex()}")
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
