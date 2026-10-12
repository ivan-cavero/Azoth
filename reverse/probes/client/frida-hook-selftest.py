#!/usr/bin/env python3
"""Attach ONE hook at a time to the live client and check it stays responsive.

WHY. A combined version of frida-player-components.py froze the client between the
splash gate and character select (`New World (Not Responding)`), while the same run
with no probe reached the world. Before trusting any of those hooks this isolates
them: each step attaches one counter-only hook, calls a trivial RPC, and reports
whether the window still answers.

Read-only: every hook is a bare counter. No memory reads, no calls into the client.

Usage:
  python reverse/probes/client/frida-hook-selftest.py
  python reverse/probes/client/frida-hook-selftest.py --steps lookup,add,byname
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import time
from pathlib import Path

import frida

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

HOOKS = {
    "lookup": 0x1413FB700,
    "add": 0x1413789C0,
    "byname": 0x141416740,
}

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => base.add(v - 0x140000000);
const counts = {};
function hook(name, va) {
  counts[name] = 0;
  Interceptor.attach(rva(va), { onEnter() { counts[name]++; } });
}
rpc.exports = {
  step(names, vas) {
    for (let i = 0; i < names.length; i++) hook(names[i], vas[i]);
    return Object.keys(counts);
  },
  stats() { return counts; }
};
send({ ev: 'ready', base: base.toString(16) });
"""


def responsive(pid: int) -> bool:
    """Ask the OS whether the window still pumps messages."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    result = {"hwnd": None}

    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        result["hwnd"] = hwnd
        return False

    user32.EnumWindows(proc(cb), None)
    if result["hwnd"] is None:
        return False
    # SendTimeoutMessage would perturb the client; GetWindowLong on GWL_STYLE is a
    # cheap proxy: a hung window cannot complete this call, so give it a deadline.
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            style = user32.GetWindowLongW(result["hwnd"], -16)
            if style != 0:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="lookup,add,byname")
    ap.add_argument("--settle", type=float, default=8.0)
    args = ap.parse_args()

    spec = importlib.util.spec_from_file_location("si", str(ROOT / "scripts" / "send-input.py"))
    simod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(simod)

    wins = simod.find_windows("New World")
    if not wins:
        print("no New World window")
        return 1
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(wins[0][0], ctypes.byref(pid))
    pid = pid.value
    print(f"target pid {pid}")
    print(f"responsive before any hook: {responsive(pid)}")

    session = frida.attach(pid)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("  js:", m.get("payload") if m.get("type") == "send" else m))
    script.load()

    names = [s.strip() for s in args.steps.split(",") if s.strip()]
    for name in names:
        if name not in HOOKS:
            print(f"unknown step {name}")
            continue
        print(f"\n--- attaching {name} (0x{HOOKS[name]:x}) ---")
        ok = script.exports_sync.step([name], [HOOKS[name]])
        print(f"  attached: {ok}")
        time.sleep(args.settle)
        stats = script.exports_sync.stats()
        print(f"  calls after {args.settle:.0f}s: {stats}")
        alive = responsive(pid)
        print(f"  responsive: {alive}")
        if not alive:
            print(f"  *** {name} FROZE THE CLIENT -- stop here ***")
            break

    print("\nfinal stats:", script.exports_sync.stats())
    print("responsive at end:", responsive(pid))
    session.detach()
    print("detached (client should stay healthy; hooks are gone)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
