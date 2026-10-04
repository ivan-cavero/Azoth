#!/usr/bin/env python3
"""Trace the record-1 -> manager-context -> component-cluster chain.

WHY. The session-232 burst probe proved the record-1 handler (FUN_141717fc0)
runs and the manager context setter (FUN_146928d80) fires twice with the
UUID-lever fix, yet the reflected-component cluster (0x141761dd0) is never
entered and the client never streams movement. This probe instruments the
CHAIN between those two facts, read-only:

  FUN_141717fc0  record-1 "local player metadata" handler
                 - log record id, the entity key it resolves, the metadata
                   pointers it writes
  FUN_146928d80  manager context setter (vtable +0x10 of FUN_141026080)
                 - log the context object stored at [mgr+8] and its +0x48/+0x50
  FUN_141570190  portrayal delegate invoker
                 - log each delegate target invoked (the portrayal->consumer
                   link the subagent found)
  0x141761dd0    component cluster entry (expected: ZERO events)
  FUN_141582430  GameTransformComponent spawner (expected: ZERO events)

All hooks are read-only Interceptor.attach; no patching. Attach to the
private runtime only (no EAC) - see research/docs/EAC.md.

Usage (run BEFORE entering the world; hooks persist across the session):
  python -u scripts/frida-record1-chain.py --stay
"""

from __future__ import annotations

import argparse
import json
import time

import frida

IMAGE_BASE = 0x140000000

HOOKS = {
    "record1": 0x141717FC0,
    "mgrSetContext": 0x146928D80,
    "portrayDelegate": 0x141570190,
    "cluster": 0x141761DD0,
    "transformSpawn": 0x141582430,
}

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev: 'error', msg: 'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  const hooks = %HOOKS%;

  // record-1 handler: log entity key + which sub-record id (edx).
  Interceptor.attach(off(hooks.record1), {
    onEnter(args) {
      this.self = args[0];
      this.recId = args[1].toInt32();
    },
    onLeave() {
      // state+0x608+rec*0x10 slot: entity+metadata pair after the call
      let slot = null;
      try {
        const table = this.self.add(0x608).readPointer();
        const cell = table.add(this.recId * 0x10);
        slot = {a: cell.readPointer().toString(), b: cell.add(8).readPointer().toString()};
      } catch (e) { slot = 'err'; }
      send({ev: 'record1', rec: this.recId, slot: JSON.stringify(slot)});
    },
  });

  // manager context setter: log the context object handed in.
  Interceptor.attach(off(hooks.mgrSetContext), {
    onEnter(args) {
      let ctx = null, a48 = null, a50 = null;
      try {
        ctx = args[1].toString();
        a48 = args[1].add(0x48).readPointer().toString();
        a50 = args[1].add(0x50).readPointer().toString();
      } catch (e) {}
      send({ev: 'mgrSetContext', ctx: ctx, ctx48: a48, ctx50: a50});
    },
  });

  // portrayal delegate invoker: log the delegate target addresses invoked.
  Interceptor.attach(off(hooks.portrayDelegate), {
    onEnter(args) {
      const list = args[0].add(0x20).readPointer();
      const count = list.readU64 ? 0 : 0;
      let head = null, n = null;
      try { head = list.readPointer().toString(); n = list.add(8).readU32(); } catch (e) {}
      send({ev: 'portrayDelegate', head: head, count: n});
    },
  });

  // cluster + transform spawner: presence only.
  for (const name of ['cluster', 'transformSpawn']) {
    Interceptor.attach(off(hooks[name]), {
      onEnter(args) {
        let flag = null;
        try { flag = args[0].add(8).readU8(); } catch (e) { flag = 'err'; }
        send({ev: name, obj: args[0].toString(), flag: flag,
              ret: this.returnAddress.sub(base).toString(16)});
      },
    });
  }
  send({ev: 'ready', base: base.toString(16)});
  // Alive ping: distinguishes "hooked but no events" from "script dead".
  let ticks = 0;
  setInterval(() => { ticks += 1; send({ev: 'alive', ticks: ticks}); }, 5000);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stay", action="store_true", help="do not exit after 15 min")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    import ctypes
    import importlib.util
    import pathlib

    here = pathlib.Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("si", here / "send-input.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    find_windows = mod.find_windows

    wins = find_windows("New World")
    if not wins:
        print("no New World window; launch the game first")
        return 1
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(wins[0][0], ctypes.byref(pid))
    print(f"attaching to pid {pid.value}")

    session = frida.attach(pid.value)
    script = session.create_script(
        JS.replace("%HOOKS%", json.dumps(HOOKS))
    )
    out_path = here.parent / "sessions" / f"record1-chain-{int(time.time())}.jsonl"
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
