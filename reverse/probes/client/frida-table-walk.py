#!/usr/bin/env python3
"""Walk the manager's entity-id table with the layout FUN_146801040 really uses.

From a local per-build decompile of the manager's slot lookup:

    lVar1 = *(mgr + 0x110);                  // bucket array
    uVar2 = *(mgr + 0x108) & random();       // bucket index
    head  = *(lVar1 + 8 + uVar2 * 0x10);     // cell.head  -> cell+0x08
    count = *(lVar1 +     uVar2 * 0x10);     // cell.count -> cell+0x00
    for node in chain(head), up to count:
        if (node[2] == *(mgr+8))  -> actor = node[5]

so each 0x10-byte cell is {u64 count, node* head} and each node is
    +0x00 next, +0x10 entity id, +0x28 actor.
The first attempt at this walk had the cell fields swapped and chased a
bogus pointer (AV at 0x2); this version matches the disassembly.

The bucket count is not stored explicitly, but mgr+0x108 is the index mask,
so buckets = mask + 1 when the mask is a full low-bit run.
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
let best = null;

Interceptor.attach(GATE, { onEnter(args) { if (mgr === null) mgr = args[0]; } });

function walk() {
  if (mgr === null) { send({ev: 'waiting'}); return; }
  try {
    const cells = mgr.add(0x110).readPointer();
    const mask = mgr.add(0x108).readU64();
    if (cells.isNull()) { send({ev: 'no-table'}); return; }
    // mask is a low-bit run -> bucket count
    let nBuckets = Number(mask) + 1;
    if (!isFinite(nBuckets) || nBuckets <= 0) nBuckets = 256;
    let total = 0, ids = [], nonEmpty = 0;
    for (let i = 0; i < nBuckets; i++) {
      const cell = cells.add(i * 0x10);
      const count = Number(cell.readU64());
      const head = cell.add(8).readPointer();
      if (count === 0 || head.isNull()) continue;
      nonEmpty++;
      total += count;
      let node = head, guard = 0;
      while (!node.isNull() && guard < 8192) {
        const id = node.add(0x10).readU64();
        if (ids.length < 32) {
          ids.push({ b: i, id: id.toString(), node: node.toString() });
        }
        node = node.readPointer();
        guard++;
      }
    }
    const payload = {ev: 'walk', mask: mask.toString(), buckets: nBuckets,
                     nonEmpty: nonEmpty, total: total, ids: ids};
    if (!best || total > best.total) { best = payload; send(payload); }
  } catch (e) { send({ev: 'walk-error', err: String(e)}); }
}

setInterval(walk, 4000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] entity table walk v2 (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
