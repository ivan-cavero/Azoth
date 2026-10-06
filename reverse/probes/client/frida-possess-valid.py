#!/usr/bin/env python3
"""Possess a node that already has a real actor.

[mgr+8] is the entity id FUN_146801040 looks up (compared to node+0x10).
The ready byte is *[mgr+0x10]. Id 13 is the stub whose actor vtable is NULL;
writing that id crashes inside the actor. The other nodes carry vtable
nw+8033f90. This writes one of those ids and keeps the ready byte alive
for the life of the process.

Read-only until a valid actor exists, then one write.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
const off = (p) => {
  try {
    if (p.isNull()) return 'null';
    const d = p.sub(base);
    if (d.compare(ptr(0)) < 0 || d.compare(ptr(mod.size)) >= 0) return p.toString();
    return 'nw+' + d.toString(16);
  } catch (e) { return '?'; }
};

const GATE = at(0x146800d10);
let mgr = null;
let done = false;
const flag = Memory.alloc(8);
flag.writeU64(1);

Interceptor.attach(GATE, { onEnter(args) { if (mgr === null) mgr = args[0]; } });

function walk() {
  const cells = mgr.add(0x110).readPointer();
  const n = Number(mgr.add(0x108).readU64()) + 1;
  const seen = new Set();
  const good = [];
  const bad = [];
  for (let i = 0; i < n; i++) {
    let node = cells.add(i * 0x10).add(8).readPointer();
    let g = 0;
    while (!node.isNull() && g < 4096) {
      const key = node.toString();
      if (!seen.has(key)) {
        seen.add(key);
        const id = node.add(0x10).readU64();
        const actor = node.add(0x28).readPointer();
        let v0 = 'unread';
        let ok = false;
        try {
          const p = actor.readPointer();
          v0 = off(p);
          ok = !actor.isNull() && p.compare(base) >= 0 && p.compare(base.add(mod.size)) < 0;
        } catch (e) { v0 = 'av'; }
        const row = { id: id.toString(), actor: actor.toString(), v0: v0 };
        (ok ? good : bad).push(row);
      }
      node = node.readPointer();
      g++;
    }
  }
  return { good: good, bad: bad };
}

function possess() {
  if (mgr === null || done) return;
  let table;
  try { table = walk(); } catch (e) { return; }
  if (table.good.length < 8) return;
  const pick = table.good[0];
  send({ ev: 'table', good: table.good.length, bad: table.bad, sample: table.good.slice(0, 4) });
  mgr.add(0x10).writePointer(flag);
  mgr.add(8).writeU64(uint64(pick.id));
  done = true;
  send({ ev: 'POSSESSED', id: pick.id, actor: pick.actor, v0: pick.v0,
         now: mgr.add(8).readU64().toString() });
}

setInterval(function () {
  if (mgr === null) { send({ ev: 'wait-mgr' }); return; }
  if (!done) { possess(); return; }
  send({ ev: 'hold', id: mgr.add(8).readU64().toString(),
         flag: flag.readU8() });
}, 2000);
send({ ev: 'ready' });
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] will possess the first valid actor", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
