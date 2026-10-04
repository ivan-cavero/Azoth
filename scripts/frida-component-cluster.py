#!/usr/bin/env python3
"""Probe the reflected-component instantiation cluster (read-only).

WHY. The replayed session renders the world through the portrayal route only:
the burst probe counted 0 calls to the actor factory FUN_141563e20, and the
component cluster that would create a real GameTransformComponent /
GameRigidBodyComponent (FUN_141761dd0-0x141763df4, landmarks in
research/derived/symbols.json:component_cluster_table_driven) is never
reached. Movement needs a real component-graph entity, so we need to know
(1) whether the cluster is EVER entered, (2) by which return address (the
data-table entry that invokes it), and (3) what the create-vs-lookup byte
([container+8]) reads on those calls.

Hooks (all read-only, attach to the private runtime only, no EAC):
  0x141761dd0  cluster entry          - log arg0, byte [+8], return address
  0x141582430  GameTransformComponent spawner - same, plus the branch taken
  0x141582690  GameTransformComponentClientFacet spawner - same

Usage:
  python scripts/frida-component-cluster.py            # attach to running game
  python scripts/frida-component-cluster.py --stay     # keep alive after bursts
"""

from __future__ import annotations

import argparse
import json
import time

import frida

IMAGE_BASE = 0x140000000

HOOKS = (
    ("cluster", 0x141761DD0),
    ("transform", 0x141582430),
    ("transform-client-facet", 0x141582690),
)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev: 'error', msg: 'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  const hooks = %HOOKS%;
  for (const [name, va] of hooks) {
    Interceptor.attach(off(va), {
      onEnter(args) {
        const p = args[0];
        let flag = null;
        try { flag = p.add(8).readU8(); } catch (e) { flag = 'err'; }
        send({
          ev: name,
          obj: p.toString(),
          flag: flag,
          ret: this.returnAddress.sub(base).toString(16),
        });
      },
    });
  }
  send({ev: 'ready', base: base.toString(16)});
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stay", action="store_true", help="do not exit after 10 min")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    import importlib.util
    import pathlib
    import sys

    here = pathlib.Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("si", here / "send-input.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    find_windows = mod.find_windows

    wins = find_windows("New World")
    if not wins:
        print("no New World window; launch the game first")
        return 1
    import ctypes

    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(wins[0][0], ctypes.byref(pid))
    print(f"attaching to pid {pid.value}")

    session = frida.attach(pid.value)
    script = session.create_script(
        JS.replace(
            "%HOOKS%",
            json.dumps([[n, v] for n, v in HOOKS]),
        )
    )
    out_path = here.parent / "sessions" / f"component-cluster-{int(time.time())}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = out_path.open("a", encoding="utf-8")

    def on_message(message, data):
        if message.get("type") == "send":
            payload = message["payload"]
            print(json.dumps(payload))
            out.write(json.dumps(payload) + "\n")
            out.flush()
        elif message.get("type") == "error":
            print("script error:", message.get("description", "")[:300])

    script.on("message", on_message)
    script.load()
    print(f"probes live; log -> {out_path}")
    try:
        deadline = time.time() + (args.timeout if not args.stay else 10**9)
        while time.time() < deadline:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
