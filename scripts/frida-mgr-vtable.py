#!/usr/bin/env python3
"""Find the manager method that creates/binds the local player.

The spawn gate (FUN_146800d10) receives the manager object as `this` and
reads [this+8] (local player entity) plus [this+0x10] (ready holder). Those
slots stay NULL while the world snapshot now arrives complete, so the bind
must come from one of the manager's own virtual methods.

Strategy: capture `this` from the gate, read its vtable, then attach a
counter to every distinct vtable slot. Whichever slot fires during the
world load (and especially right after the type 0x8 bundles) is the binder.
If a slot is hot but never writes +8, dump that slot's bytes so it can be
mapped back to a function in the disassembly.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const off = (p) => 'nw+' + p.sub(base).toString(16);

const GATE = base.add(rva(0x146800d10));
let mgr = null;
const counts = {};
const hooked = new Set();

function hookVtable() {
  if (mgr === null) return;
  const vt = mgr.readPointer();
  send({ev: 'vtable', mgr: mgr.toString(), vt: off(vt)});
  // 0x100 bytes = 32 slots; report which ones exist and hook them.
  for (let i = 0; i < 32; i++) {
    let fn;
    try { fn = vt.add(i * 8).readPointer(); } catch (e) { break; }
    if (fn.isNull()) break;
    const key = fn.toString();
    send({ev: 'slot', index: i, offset: '0x' + (i * 8).toString(16), fn: off(fn)});
    if (hooked.has(key)) continue;
    hooked.add(key);
    try {
      Interceptor.attach(fn, {
        onEnter() {
          counts['0x' + (i * 8).toString(16)] = (counts['0x' + (i * 8).toString(16)] || 0) + 1;
        }
      });
    } catch (e) {
      send({ev: 'hook-failed', slot: i, err: String(e)});
    }
  }
  // One-shot: dump the first 0x40 bytes of the manager for later layout work.
  try {
    const bytes = mgr.readByteArray(0x60);
    send({ev: 'mgr-bytes',
          hex: Array.from(new Uint8Array(bytes))
            .map((b) => b.toString(16).padStart(2, '0')).join(' ')});
  } catch (e) {}
}

Interceptor.attach(GATE, {
  onEnter(args) {
    if (mgr === null) {
      mgr = args[0];
      hookVtable();
    }
    try {
      const ent = mgr.add(8).readPointer();
      if (!ent.isNull()) send({ev: 'ENTITY-BOUND', ent: ent.toString()});
    } catch (e) {}
  }
});

setInterval(function () {
  send({ev: 'counts', counts: counts});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] manager vtable armed (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
