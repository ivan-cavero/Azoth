#!/usr/bin/env python3
"""Bind the local player to a node that has a REAL actor.

Revised model (2026-09-24). FUN_146801040 compares `*(mgr+8)` against
`node[2]` == `*(node + 0x10)` and then dereferences `node[5]` ==
`*(node + 0x28)` as the actor. The manager table holds 14 nodes:

  * 13 of them: node+0x10 = a large value (2.2e12 range), node+0x28 = an
    actor whose first qword is a real vtable (nw+8033f90) -> USABLE.
  * 1 of them: node+0x10 = 13, node+0x28 = garbage (ffff8008...) -> the
    one injected earlier, which is what crashed the getter at +0x104285d.

So the earlier "id 13" was the wrong node. Binding mgr+8 to the id of any
node whose actor is well formed should make the getter resolve a real
actor instead of dereferencing garbage. This probe picks the first node
with a readable, in-image vtable and writes its id.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const GATE = base.add(rva(0x146800d10));
let mgr = null, done = false;

Interceptor.attach(GATE, { onEnter(args) { if (mgr === null) mgr = args[0]; } });

function pickNode() {
  const cells = mgr.add(0x110).readPointer();
  const n = Number(mgr.add(0x108).readU64()) + 1;
  const seen = new Set();
  const good = [], bad = [];
  for (let i = 0; i < n; i++) {
    let node = cells.add(i * 0x10).add(8).readPointer();
    let guard = 0;
    while (!node.isNull() && guard < 4096) {
      const key = node.toString();
      if (!seen.has(key)) {
        seen.add(key);
        const id = node.add(0x10).readU64();
        const actor = node.add(0x28).readPointer();
        let ok = false, v0 = null;
        try {
          v0 = actor.readPointer();
          // a real object: vtable points into the module image
          ok = !actor.isNull() && v0.compare(base) >= 0 &&
               v0.compare(base.add(mod.size)) < 0;
        } catch (e) {}
        (ok ? good : bad).push({ id: id.toString(), node: key,
                                 actor: actor.toString(),
                                 v0: v0 ? off(v0) : null });
      }
      node = node.readPointer();
      guard++;
    }
  }
  return { good: good, bad: bad };
}

function off(p) {
  const d = p.sub(base);
  return (d.compare(ptr(0)) < 0) ? p.toString() : 'nw+' + d.toString(16);
}

function act() {
  if (mgr === null || done) return;
  const r = pickNode();
  if (r.good.length === 0) { send({ev: 'no-good', bad: r.bad.length}); return; }
  // pick the good node with the smallest id for determinism
  r.good.sort((a, b) => (BigInt(a.id) < BigInt(b.id) ? -1 : 1));
  const pick = r.good[0];
  // ready flag
  let rp = mgr.add(0x10).readPointer();
  if (rp.isNull()) {
    const b = Memory.alloc(1); b.writeU8(1);
    mgr.add(0x10).writePointer(b);
  } else { try { rp.writeU8(1); } catch (e) {} }
  // id is a u64; write it as two u32 halves to avoid Int64/UInt64 API mixups
  const hi = Number((BigInt(pick.id) >> 32n) & 0xFFFFFFFFn);
  const lo = Number(BigInt(pick.id) & 0xFFFFFFFFn);
  mgr.add(8).writeU32(hi);
  mgr.add(12).writeU32(lo);
  done = true;
  send({ev: 'INJECTED', id: pick.id, node: pick.node, actor: pick.actor,
        v0: pick.v0, goodCount: r.good.length, badCount: r.bad.length});
}

setInterval(function () {
  if (mgr === null) return;
  if (!done) { act(); return; }
  const id = (mgr.add(12).readU32() * 0x100000000 + mgr.add(8).readU32()).toString();
  send({ev: 'state', id: id});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] binding to a node with a valid actor (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
