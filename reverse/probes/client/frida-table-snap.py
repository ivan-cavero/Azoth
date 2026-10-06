#!/usr/bin/env python3
"""Walk the local-player manager table exactly like FUN_146801040 does.

Attaches to NewWorld.exe, captures mgr from the gate (FUN_146800d10),
walks buckets at mgr+0x110 (count = *(mgr+0x108)+1 cells of {u64 count, node*}),
each node {+0x00 next, +0x10 id, +0x28 actor}, actor vtable = *actor.

Reports: [mgr+8], ready byte, node count, per-node id + actor-vtable check.
One-shot JSON to stdout + log file.
"""

from __future__ import annotations

import json
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
Interceptor.attach(GATE, { onEnter(args) { if (mgr === null) mgr = args[0]; } });

function snapshot() {
  if (mgr === null) return {mgr: null};
  const out = {mgr: mgr.toString(), id: mgr.add(8).readU64().toString()};
  try {
    const rp = mgr.add(0x10).readPointer();
    out.readyPtr = rp.toString();
    out.ready = rp.isNull() ? -1 : rp.readU8();
  } catch (e) { out.ready = 'err'; }
  const nodes = [];
  try {
    const cells = mgr.add(0x110).readPointer();
    const n = Number(mgr.add(0x108).readU64()) + 1;
    out.buckets = n;
    const seen = new Set();
    for (let i = 0; i < n; i++) {
      let node = cells.add(i * 0x10).add(8).readPointer();
      let g = 0;
      while (!node.isNull() && g < 4096) {
        const k = node.toString();
        if (!seen.has(k)) {
          seen.add(k);
          const id = node.add(0x10).readU64().toString();
          const actor = node.add(0x28).readPointer();
          let v0 = 'null-actor', ok = false;
          try {
            if (!actor.isNull()) {
              const v = actor.readPointer();
              v0 = off(v);
              ok = v.compare(base) >= 0 && v.compare(base.add(mod.size)) < 0;
            }
          } catch (e) { v0 = 'av'; }
          nodes.push({id: id, v0: v0, ok: ok});
        }
        node = node.readPointer();
        g++;
      }
    }
  } catch (e) { out.walkErr = String(e).slice(0, 100); }
  out.nodes = nodes;
  out.good = nodes.filter((x) => x.ok).length;
  return out;
}

setTimeout(function () { send({ev: 'snap', snap: snapshot()}); }, 3000);
send({ev: 'ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on(
        "message",
        lambda m, _d: print(
            json.dumps(m.get("payload")) if isinstance(m.get("payload"), dict) else (m.get("payload") or m),
            flush=True,
        ),
    )
    script.load()
    print("[table] snapshot in 3s", flush=True)
    time.sleep(8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
