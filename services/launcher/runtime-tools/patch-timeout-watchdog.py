#!/usr/bin/env python3
"""Stop the client's InGame state watchdog from tearing the world down.

WHY. Once the replay stream ends, the client sits in the `InGame` state and a
per-state watchdog counts intervals in which the message the state expects did
not arrive. Measured live 2026-09-27 with a Frida probe on that function:

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

    1.400  146445ef5  xor eax, eax
    1.400  146445ef7  mov qword ptr [rbx + 0x18], rax   ; reset both counters
    1.400  146445efb  mov al, 1                         ; <- return TRUE = timed out
    1.400  146445f0c  32 c0                            ; the other path: f1c++

    1.460  1464471af  xor eax, eax                    (same six-byte run,
    1.460  1464471b1  mov qword ptr [rbx + 0x18], rax   moved +0x11BA)
    1.460  1464471b5  mov al, 1                         ; <- patch here
    1.460  1464471c5  ff c0 / 89 43 1c / 32 c0        ; f1c++ / return false

Patching `mov al, 1` to `mov al, 0` keeps the bookkeeping (the counters still
reset) but never reports a timeout, so the state machine no longer forces a
disconnect. This is the same class of in-memory, private-runtime patch as
`patch-predicate-flag.py`; it is a sandbox affordance, not a protocol fix — the
proper fix is to keep sending the messages the InGame state expects, which is
what `rep.py`'s post-replay heartbeat (`AZOTH_REPLAY_HEARTBEAT`) starts doing
(it already stretched the window from ~44 s to ~58 s).

HOW THE 1.460 SITE WAS RE-DERIVED (2026-10-22). Not from the old address: in
1.460 `0x146445EFB` is the middle of an unrelated `lea`. The anchor is the
counter reset itself, `33 C0 48 89 43 18 B0 01`, which is a single unique match
in the whole 1.460 .text (`bytepat.py watchdog-return`), and the function that
contains it, `FUN_1464470d0`, is the watchdog: it logs
`State(...) is timeout : frames ...` and resets `[tracker+0x18]`/`[+0x1c]`
before returning 1 (corpus `reverse/builds/30fe6461.../corpus`, shard block
1464470d0-1464471de).

Restore by restarting the game. In-memory only, private runtime only (no EAC)
— see research/docs/EAC.md for the scoped ban.

Usage:
  python services/launcher/runtime-tools/patch-timeout-watchdog.py           # apply
  python services/launcher/runtime-tools/patch-timeout-watchdog.py --revert  # restore bytes
  python services/launcher/runtime-tools/patch-timeout-watchdog.py --check   # static, no game
  python services/launcher/runtime-tools/patch-timeout-watchdog.py --timeout 240
"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_sites  # noqa: E402
from build_sites import BUILD_1_400, BUILD_1_460, Site  # noqa: E402

TAG = "timeout-watchdog"

ORIG = bytes.fromhex("B001")  # mov al, 1  -> "timed out"
WANT = bytes.fromhex("B000")  # mov al, 0  -> never report a timeout

SITES: dict[str, tuple[Site, ...]] = {
    BUILD_1_400: (Site(0x146445EFB, ORIG, WANT, "InGame watchdog return value"),),
    # The 1.460 site is 0x1464471BA, not 0x1464471B5: the declared address landed
    # on the preceding `33 c0` (xor eax,eax) and was 5 bytes early. `b0 01` alone
    # occurs 64,128 times in the image, so only the surrounding instruction run
    # identifies it — `33 c0 48 89 43 18 b0 01` (xor eax,eax ; mov [rbx+0x18],rax ;
    # mov al,1) occurs exactly once, at foff 0x64467b5.
    BUILD_1_460: (Site(0x1464471BB, ORIG, WANT, "InGame watchdog return value"),),
}

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

k32 = ctypes.windll.kernel32


def _find_windows():
    input_helper = HERE.parents[2] / "scripts" / "gui" / "send-input.py"
    spec = importlib.util.spec_from_file_location("si", input_helper)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_windows


def patch(pid: int, sites: tuple[Site, ...], revert: bool = False) -> bool:
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
        print(f"[{TAG}] module base {base_addr:#x}")
        return build_sites.apply_in_process(h, base_addr, sites, revert, TAG)
    finally:
        k32.CloseHandle(h)


def main() -> int:
    if "--check" in sys.argv:
        return build_sites.report_check(SITES, TAG)
    revert = "--revert" in sys.argv
    timeout = 240
    if "--timeout" in sys.argv:
        timeout = int(sys.argv[sys.argv.index("--timeout") + 1])

    build, _exe, note = build_sites.identify(SITES)
    sites = SITES[build]
    print(f"[{TAG}] build sha256={build}")
    print(f"[{TAG}] {note}")
    for site in sites:
        print(f"[{TAG}] {site.detail()}")

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
        if patch(pid.value, sites, revert=revert):
            return 0
        time.sleep(2)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
