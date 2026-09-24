#!/usr/bin/env python3
"""Inject the local-player entity id into the manager and open the gate.

Established 2026-09-24 by walking the manager's own table exactly as
FUN_146801040 does (mgr+0x110 buckets of 0x10: {count, head}; node layout
+0x00 next, +0x10 entity id, +0x28 actor):

    bucket mask 0x15 -> 16 buckets, 13 entries
    id 13         node 0x1d1c0310038  <-- allocated in the SAME heap block
                                            as the manager itself (0x1d1c03xxxx)
    the rest are 2.2e12-range values   <-- those are actor pointers, not ids

So the player's own node is the one whose id is a small integer and whose
node sits beside the manager. This script:

  1. re-walks the table,
  2. picks the candidate (small id + node near the manager),
  3. writes it to [mgr+8],
  4. ensures [mgr+0x10] points at a byte that is non-zero,
  5. logs the result and keeps watching, because the gate may clear it if
     the client decides the id is bogus.

This is the same thing the official "you are entity X" message does, just
supplied locally, so it is safe to iterate: worst case the client rejects
the id and we learn the real id differs.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const GATE = base.add(rva(0x146800d10));
let mgr = null;
let injected = false;
let flagByte = null;

Interceptor.attach(GATE, {
  onEnter(args) { if (mgr === null) mgr = args[0]; }
});

function findPlayerNode() {
  const cells = mgr.add(0x110).readPointer();
  const nBuckets = Number(mgr.add(0x108).readU64()) + 1;
  let best = null;
  for (let i = 0; i < nBuckets; i++) {
    const cell = cells.add(i * 0x10);
    const count = Number(cell.readU64());
    let node = cell.add(8).readPointer();
    let guard = 0;
    while (!node.isNull() && guard < 8192) {
      const id = node.add(0x10).readU64().toNumber();
      // player node: small integer id, allocated beside the manager
      const near = Math.abs(node.sub(mgr).toInt32()) < 0x100000;
      if (id > 0 && id < 4096 && near) {
        if (!best || id < best.id) best = { id: id, node: node.toString() };
      }
      node = node.readPointer();
      guard++;
    }
  }
  return best;
}

function inject() {
  if (mgr === null || injected) return;
  const c = findPlayerNode();
  if (c === null) { send({ev: 'no-candidate'}); return; }
  // [mgr+0x10] must point at a non-zero byte (the "ready" flag).
  let rp = mgr.add(0x10).readPointer();
  if (rp.isNull()) {
    flagByte = Memory.alloc(1);
    flagByte.writeU8(1);
    rp = flagByte;
    mgr.add(0x10).writePointer(rp);
    send({ev: 'ready-flag-created', ptr: rp.toString()});
  } else {
    try { rp.writeU8(1); send({ev: 'ready-flag-set', ptr: rp.toString()});
    } catch (e) { send({ev: 'flag-error', err: String(e)}); }
  }
  mgr.add(8).writeU64(c.id);
  injected = true;
  send({ev: 'INJECTED', id: c.id, node: c.node,
        mgr: mgr.toString(), slot: mgr.add(8).toString()});
}

setInterval(function () {
  if (mgr === null) return;
  if (!injected) { inject(); return; }
  const id = mgr.add(8).readU64().toString();
  send({ev: 'state', id: id, ready: mgr.add(0x10).readPointer().toString()});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] injecting local-player entity id (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
