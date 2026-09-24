#!/usr/bin/env python3
"""Inject a valid actor id AND instrument the second gate that crashed.

Sequence found on 2026-09-24:
  * injecting a node id whose actor is well formed gets the spawn gate
    (0x146800d10) past its check; the client then faults at
    NewWorld+0x16af4b8, which is
        sub rsp,0x28 / add rcx,0x60 / cmp qword [rcx],0 / je / mov rax,[rcx+8]
        cmp byte [rax],0 / call 0x14165b620
    i.e. a second "is it ready" gate on `this+0x60`, where `this` is a
    DIFFERENT object (not the manager at 0x1d1c03xxxx).
  * So gate 1 now passes and the flow reaches gate 2, whose owner object
    was never constructed.

This probe: injects the id, hooks both gates, and dumps gate 2's `this`
plus a window of the object so the missing field can be identified instead
of guessed.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const off = (p) => { const d = p.sub(base); return d.compare(ptr(0)) < 0 ? p.toString() : 'nw+' + d.toString(16); };

const GATE1 = base.add(rva(0x146800d10));
const GATE2 = base.add(rva(0x1416af4b0));

let mgr = null, injected = false, g2 = 0;

function walkGood() {
  const cells = mgr.add(0x110).readPointer();
  const n = Number(mgr.add(0x108).readU64()) + 1;
  const seen = new Set();
  for (let i = 0; i < n; i++) {
    let node = cells.add(i * 0x10).add(8).readPointer();
    let guard = 0;
    while (!node.isNull() && guard < 4096) {
      const k = node.toString();
      if (!seen.has(k)) {
        seen.add(k);
        const id = node.add(0x10).readU64().toString();
        const actor = node.add(0x28).readPointer();
        let good = false;
        try { const v0 = actor.readPointer(); good = !actor.isNull() && v0.compare(base) >= 0 && v0.compare(base.add(mod.size)) < 0; } catch (e) {}
        if (good) return { id: id, node: k, actor: actor.toString() };
      }
      node = node.readPointer(); guard++;
    }
  }
  return null;
}

function inject() {
  const g = walkGood();
  if (g === null) return false;
  let rp = mgr.add(0x10).readPointer();
  if (rp.isNull()) { const b = Memory.alloc(1); b.writeU8(1); mgr.add(0x10).writePointer(b); }
  else { try { rp.writeU8(1); } catch (e) {} }
  const v = BigInt(g.id);
  mgr.add(8).writeU32(Number((v >> 32n) & 0xFFFFFFFFn));
  mgr.add(12).writeU32(Number(v & 0xFFFFFFFFn));
  injected = true;
  send({ev: 'INJECTED', id: g.id, actor: g.actor});
  return true;
}

Interceptor.attach(GATE1, {
  onEnter(args) { if (mgr === null) mgr = args[0]; }
});

Interceptor.attach(GATE2, {
  onEnter(args) {
    g2++;
    if (g2 <= 3) {
      const this_ = args[0];
      let win = null, at60 = null;
      try {
        const bytes = this_.readByteArray(0x80);
        win = Array.from(new Uint8Array(bytes)).map((b) => b.toString(16).padStart(2, '0')).join(' ');
        at60 = this_.add(0x60).readPointer().toString();
      } catch (e) { win = 'err:' + String(e); }
      send({ev: 'GATE2', n: g2, this: this_.toString(), at60: at60, window: win});
    }
  }
});

setInterval(function () {
  if (mgr === null) return;
  if (!injected) { inject(); return; }
  send({ev: 'state', g2: g2});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] inject + instrument gate2 (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
