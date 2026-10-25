#!/usr/bin/env python3
"""Give ClientContext::Initialize the "ok" flag it needs to not self-clean.

WHY (measured, not guessed). LoadContextAndLevel (1.400 0x146448CD0, 1.460
0x146449F90) reads a virtual predicate three times and feeds the FIRST result to
Initialize as its 7th argument:

    1.460  14644a14c  call qword ptr [rdx + 0x88]   ; predicate (receiver = pGame+0x28)
    1.460  14644a152  movzx ebx, al                 ; ebx = result1
    ...
    1.460  14644a18a  mov byte ptr [rsp + 0x30], bl ; -> 7th arg of Initialize
    1.460  14644a1a8  call 0x14171c670              ; ClientContext::Initialize

Inside Initialize the flag is the ONLY thing between the "Initialize()" log and
the "Cleanup()" log:

    1.460  14171c851  cmp byte ptr [rsp + 0x110], 0   ; == the caller's [rsp+0x30]
    1.460  14171c859  jne 0x14171c863                 ; NON-ZERO -> skip
    1.460  14171c85b  mov rcx, rdi                    ; rdi = the context argument
    1.460  14171c85e  call 0x1416841c0                ; logs "Cleanup()" on the SAME ctx

Measured live with Frida (reverse/probes/client/frida-predicate-probe.py, first world attempt
of a fresh process): the predicate returns 0. So Initialize takes the cleanup
branch on the context it was just handed, and every later state bundle is
dropped with `clientContext == nullptr` — black screen, no local player actor,
`connection_player_timeout` at ~120 s.

THE ARCHIVED PATCH IS INVERTED. scripts/patch-context-gate.py wrote
`31 DB 90` (xor ebx, ebx) at 1.400 0x146448E92, i.e. it FORCES the flag to 0 —
the exact value that triggers the self-cleanup. That is why "forcing the
predicate did not stop the cleanup" (its own header admits it): it was forcing
the wrong value.

The third predicate call must ALSO be neutralised, because the same getter on
the same object is read again right after Initialize and a non-zero there takes
the failure branch:

    1.460  14644a227  call qword ptr [rax + 0x88]   ; predicate again
    1.460  14644a230  test al, al
    1.460  14644a232  jne 0x14644a3a1               ; non-zero -> failure branch

So both sites are patched:

  1. `0F B6 D8` (movzx ebx, al) -> `B3 01 90` (mov bl, 1 ; nop)
     Initialize receives "ok" and initialises instead of cleaning up.
  2. `0F 85 69 01 00 00` (jne) -> six NOPs
     the failure branch can never be taken.

HOW THE 1.460 SITES WERE RE-DERIVED (2026-10-22). Both sites moved; the old
addresses land inside unrelated instructions in 1.460. Neither was guessed from
a byte pattern alone:

  * site 1 anchors on `call [rdx+0x88]; movzx ebx, al; movzx edi,[r13+0x180]`
    (`bytepat.py predicate-flag-1`), a single hit in 1.460 .text at
    0x14644A14C, with the patch site six bytes later. The corpus function
    146449f90-14644a44a reads the predicate as `(**(code **)(*plStackX_18 +
    0x88))(plStackX_18)`, stores it, passes it as the 7th argument of
    `FUN_14171c670`, and the very next source line loads `param_1 + 0x180`,
    which is the `movzx edi,[r13+0x180]` the anchor matched.
  * site 2 anchors on `call [rax+0x88]; mov rcx,r13; test al,al; jne`
    (`bytepat.py predicate-flag-2`), unique at 0x14644A227, 11 bytes before the
    patch site — and the jne's rel32 is still `0x169`, exactly as on 1.400, so
    the two endpoints of the jump are the same two instructions.

Direct memory write (no Frida: its Interceptor raced during startup). Run AFTER
the game window exists. In-memory only, private runtime only (no EAC) — see
research/docs/EAC.md for the scoped ban. Restore by restarting the game.

Usage:
  python services/launcher/runtime-tools/patch-predicate-flag.py            # apply
  python services/launcher/runtime-tools/patch-predicate-flag.py --revert   # restore bytes
  python services/launcher/runtime-tools/patch-predicate-flag.py --check    # static, no game
  python services/launcher/runtime-tools/patch-predicate-flag.py --timeout 240
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

TAG = "predicate-flag"

MOVZX_EBX_AL = bytes.fromhex("0FB6D8")  # movzx ebx, al
MOV_BL_1 = bytes.fromhex("B30190")  # mov bl, 1 ; nop  -> Initialize gets "ok"
JNE_FAILURE = bytes.fromhex("0F8569010000")  # jne rel32 0x169 (failure branch)
SIX_NOP = bytes.fromhex("90" * 6)

SITES: dict[str, tuple[Site, ...]] = {
    BUILD_1_400: (
        Site(0x146448E92, MOVZX_EBX_AL, MOV_BL_1, "predicate flag -> Initialize (0 -> 1)"),
        Site(0x146448F72, JNE_FAILURE, SIX_NOP, "jne to the Cleanup failure branch"),
    ),
    BUILD_1_460: (
        Site(0x14644A152, MOVZX_EBX_AL, MOV_BL_1, "predicate flag -> Initialize (0 -> 1)"),
        Site(0x14644A232, JNE_FAILURE, SIX_NOP, "jne to the Cleanup failure branch"),
    ),
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
