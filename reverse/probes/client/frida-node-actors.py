#!/usr/bin/env python3
"""Inspect every node's actor so we pick a valid local-player id.

Injecting id 13 unblocked the gate for the first time but the client then
crashed at NewWorld+0x104285d -- the spawn-gate getter, inside the actor
deserialization. So id 13's actor is not a usable local player.

This probe does NOT write anything. It walks the manager table exactly as
FUN_146801040 does and, for every node, reports:
  * the entity id (node+0x10)
  * the actor pointer (node+0x28)
  * whether the actor is readable and what its first qwords look like
    (vtable pointer, a couple of fields)
so we can tell the real player actor from the world-entity stubs before
risking another crash.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const off = (p) => (p.sub(base).compare(ptr(0)) < 0 ? p.toString()
                                                 : 'nw+' + p.sub(base).toString(16));
const GATE = base.add(rva(0x146800d10));
let mgr = null, lastCount = -1, bestNodes = null;

Interceptor.attach(GATE, { onEnter(args) { if (mgr === null) mgr = args[0]; } });

function inspect() {
  if (mgr === null) return;
  try {
    const cells = mgr.add(0x110).readPointer();
    const n = Number(mgr.add(0x108).readU64()) + 1;
    const out = [];
    const seen = new Set();
    for (let i = 0; i < n; i++) {
      const count = Number(cells.add(i * 0x10).readU64());
      let node = cells.add(i * 0x10).add(8).readPointer();
      let guard = 0;
      while (!node.isNull() && guard < 4096) {
        const key = node.toString();
        if (!seen.has(key)) {
          seen.add(key);
          const id = node.add(0x10).readU64().toString();
          const actor = node.add(0x28).readPointer();
          let info = { id: id, node: key, actor: actor.toString(),
                       actorRead: false, actorTag: null };
          try {
            const v0 = actor.readPointer();
            const v1 = actor.add(8).readPointer();
            const w38 = actor.add(0x38).readU64();
            info.actorRead = true;
            info.actorTag = { v0: off(v0), v1: off(v1),
                              p38: w38.toString(),
                              nearMgr: Math.abs(actor.sub(mgr).toInt32()) < 0x400000 };
          } catch (e) { info.actorErr = String(e); }
          out.push(info);
        }
        node = node.readPointer();
        guard++;
      }
    }
    // Only report when the table grew past the empty/id-0 state, and remember
    // the fullest snapshot so it survives later polls.
    const real = out.filter((x) => x.id !== '0');
    if (!bestNodes || real.length > bestNodes.length) {
      bestNodes = real.map((x) => x.id);
      if (real.length) send({ev: 'nodes', count: out.length, real: real.length, nodes: out});
    }
  } catch (e) { /* table not ready yet */ }
}

setInterval(inspect, 2500);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] inspecting node actors, no writes (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
