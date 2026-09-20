#!/usr/bin/env python3
"""Probe the GameConnection FSM (FUN_14644a070) live.

Logs every state change plus, in the WaitingForPlayerSpawn case (0xd),
the three conditions that gate the InGame transition:

    cVar2 = func_0x145a923c0(param_1 + 0x130)   # player-spawn getter
    lVar6 = FUN_141026080()                     # singleton A
    lVar6 = (**(vtable+0x30))(lVar6)            # singleton A -> actor

Only state changes and case-0xd evaluations are printed, so the log
stays readable. Attach to the running private NewWorld.exe.

Usage: python scripts/frida-fsm-probe.py [--stay]
"""

from __future__ import annotations

import argparse
import sys
import time

import frida

FSM_VA = 0x14644A070
GETTER_SPAWN_VA = 0x145A923C0
SINGLETON_VA = 0x141026080

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { throw new Error('no NewWorld.exe'); }
const base = mod.base;
const off = (va) => base.add(va - 0x140000000);

const FSM = off(0x14644a070);
const SPAWN = off(0x145a923c0);
const SINGLETON = off(0x141026080);

let lastState = -1;

Interceptor.attach(FSM, {
  onEnter(args) {
    this.self = args[0];
    this.stateIn = this.self.add(0x1530).readS32();
  },
  onLeave(retval) {
    const s = this.self.add(0x1530).readS32();
    if (s !== this.stateIn || s !== lastState) {
      if (s !== lastState) {
        send({ev: 'state', from: this.stateIn, to: s});
        lastState = s;
      }
    }
    if (s === 0xd) {
      // Evaluate the three gates of the InGame transition.
      let spawn = null, sing = null, actor = null;
      try {
        const spawnFn = new NativeFunction(SPAWN, 'uint8', ['pointer']);
        spawn = spawnFn(this.self.add(0x130));
      } catch (e) { spawn = 'err:' + e; }
      try {
        const singFn = new NativeFunction(SINGLETON, 'pointer', []);
        sing = singFn();
        if (!sing.isNull()) {
          const vt = sing.readPointer();
          const fn = vt.add(0x30).readPointer();
          const call = new NativeFunction(fn, 'pointer', ['pointer']);
          actor = call(sing);
        } else { actor = ptr(0); }
      } catch (e) { actor = 'err:' + e; }
      send({ev: 'gate13', spawn: spawn, singleton: String(sing), actor: String(actor)});
    }
  }
});
send({ev: 'ready', base: String(base)});
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stay", action="store_true")
    ap.add_argument("--seconds", type=float, default=0)
    args = ap.parse_args()

    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)

    def on_message(msg, data):
        if msg.get("type") == "send":
            print("[fsm]", msg["payload"], flush=True)
        else:
            print("[fsm]", msg, flush=True)

    script.on("message", on_message)
    script.load()
    print("[fsm] loaded", flush=True)
    if args.seconds:
        time.sleep(args.seconds)
    elif args.stay:
        try:
            sys.stdin.read()
        except KeyboardInterrupt:
            pass
    else:
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())