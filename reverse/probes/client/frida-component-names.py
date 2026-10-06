#!/usr/bin/env python3
"""Log every component the client creates BY NAME during world entry (read-only).

WHY. Movement is blocked because the local player has no physics components. The
player's 124 components come from the local slice, not the wire; the open question
is whether the client EVER tries to create GameRigidBody/CharacterController and,
if so, for which entity. This hooks the by-name reflected-component add
(FUN_141416740, hashes a NUL-terminated name; see DECOMP-BACKLOG / levers.md) plus
the cluster entry and the transform spawners, so we can read the component names
the client actually requests.

Private runtime only (no EAC). All hooks are read-only.

Usage:
  python scripts/frida-component-names.py            # attach to running game
  python scripts/frida-component-names.py --timeout 400
"""

from __future__ import annotations

import argparse
import ctypes
import json
import time
from pathlib import Path

import frida

HOOKS = (
    ("byname", 0x141416740),          # add reflected component by NAME (args[2]=char*)
    ("cluster", 0x141761DD0),         # cluster entry
    ("transform", 0x141582430),       # GameTransformComponent spawner
    ("xfacet", 0x141582690),
    ("xserver", 0x1415828F0),
)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  for (const [name, va] of %HOOKS%) {
    Interceptor.attach(off(va), {
      onEnter(args) {
        let name_arg = null;
        if (name === 'byname') {
          try {
            const p = args[2];
            name_arg = (p.isNull()) ? null : p.readUtf8String();
          } catch (e) { name_arg = '<read-err>'; }
        }
        let flag = null;
        try { flag = args[0].add(8).readU8(); } catch (e) { flag = null; }
        send({ev: name, obj: args[0].toString(), name: name_arg, flag: flag,
              ret: this.returnAddress.sub(base).toString(16)});
      }
    });
  }
  send({ev: 'ready', base: base.toString(16)});
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    import importlib.util

    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("si", here / "send-input.py")
    simod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(simod)

    wins = simod.find_windows("New World")
    if not wins:
        print("no New World window")
        return 1
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(wins[0][0], ctypes.byref(pid))
    print(f"attaching to pid {pid.value}", flush=True)

    session = frida.attach(pid.value)
    script = session.create_script(JS.replace("%HOOKS%", json.dumps([list(h) for h in HOOKS])))
    out_path = here.parent / "sessions" / f"component-names-{int(time.time())}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = out_path.open("a", encoding="utf-8")

    def on_message(message, data):
        if message.get("type") == "send":
            print(json.dumps(message["payload"]), flush=True)
            out.write(json.dumps(message["payload"]) + "\n")
            out.flush()
        elif message.get("type") == "error":
            print("script error:", message.get("description", "")[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"probes live; log -> {out_path}", flush=True)
    try:
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
