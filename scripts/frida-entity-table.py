#!/usr/bin/env python3
"""Inspect the manager's entity hash table at this+0x110.

FUN_146801040 (vtable slot 0x78) resolves the local player by taking
`this+8` as an entity id and walking a bucket chain whose base is at
`this+0x110`. If the table is empty, no actor can ever be found; if it is
populated, the world snapshot DID create replicas and the failure is
purely the missing "this is me" binding.

Reports: the table pointer, the bucket count / mask, the first few bucket
heads, and how many entries chain off them, plus the manager's +8/+0x10
gate inputs for comparison.
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
let reported = false;

Interceptor.attach(GATE, {
  onEnter(args) {
    if (mgr === null) mgr = args[0];
  }
});

function dump() {
  if (mgr === null) { send({ev: 'waiting-for-gate'}); return; }
  try {
    const entId = mgr.add(8).readU64().toString();
    const readyPtr = mgr.add(0x10).readPointer().toString();
    const table = mgr.add(0x110).readPointer();
    let buckets = null, mask = null, heads = [], entries = 0;
    if (!table.isNull()) {
      buckets = table.readU64().toString();
      // the loop does: mask = random(); idx = *(u64*)((u64*)buckets + idx*0x10)
      // so the table is an array of {hash, count, ...} 16-byte cells.
      const rows = [];
      for (let i = 0; i < 8; i++) {
        const cell = table.add(i * 0x10);
        rows.push(cell.readU64().toString() + '/' + cell.add(8).readU64().toString());
      }
      heads = rows;
      // total entries = sum of the per-row counts
      for (let i = 0; i < 8; i++) entries += Number(table.add(i * 0x10 + 8).readU64());
    }
    send({ev: 'table', mgr: mgr.toString(), entId: entId, readyPtr: readyPtr,
          table: table.toString(), buckets: buckets, cells: heads,
          entriesInFirst8: entries});
  } catch (e) {
    send({ev: 'dump-error', err: String(e)});
  }
}

setInterval(dump, 3000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] entity table dump (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
