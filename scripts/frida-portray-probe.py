#!/usr/bin/env python3
"""Watch the portrayal call that runs for every state record.

FUN_141717fc0 reaches FUN_14178db00 whether or not the StateReplication
trace level allows the "newActorId" log. The level check at +0x18 is a
trace gate (value 2 suppresses categories 3 and 4); forcing it does not
build an actor. This probe records what portrayal actually sees:

  * the qword at (metadata + 0x880), which the predicate FUN_146165f20 tests
  * whether that predicate accepts it
  * the entity table the local-player getter walks

Read-only. Attach after the private runtime is mapped.
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

const predReturn = at(0x14178db34);
let portrays = 0;
Interceptor.attach(at(0x14178db00), {
  onEnter(args) {
    portrays++;
    this.n = portrays;
    let q = null, pred = null;
    try {
      q = args[1].add(0x20).readU64().toString();
      const al = at(0x146165f20);
      // predicate reads the qword and returns a bool in al
    } catch (e) { q = 'err'; }
    this.q = q;
    if (portrays <= 40) send({ev: 'portray', n: portrays, q: q, ctx: off(args[0])});
  }
});

Interceptor.attach(at(0x146165f20), {
  onEnter(args) {
    this.fromPortray = this.returnAddress.equals(predReturn);
    if (!this.fromPortray) return;
    try { this.q = args[0].readU64().toString(); } catch (e) { this.q = 'err'; }
  },
  onLeave(ret) {
    if (!this.fromPortray) return;
    send({ev: 'pred', q: this.q, al: ret.and(0xff).toInt32()});
  }
});

const GATE = at(0x146800d10);
let mgr = null;
Interceptor.attach(GATE, { onEnter(args) { if (mgr === null) mgr = args[0]; } });

function nodes() {
  if (mgr === null) return null;
  const cells = mgr.add(0x110).readPointer();
  const n = Number(mgr.add(0x108).readU64()) + 1;
  const out = [];
  const seen = new Set();
  for (let i = 0; i < n; i++) {
    let node = cells.add(i * 0x10).add(8).readPointer();
    let guard = 0;
    while (!node.isNull() && guard < 4096) {
      const key = node.toString();
      if (!seen.has(key)) {
        seen.add(key);
        const id = node.add(0x10).readU64().toString();
        const actor = node.add(0x28).readPointer();
        let v0 = null, ok = false;
        try {
          v0 = actor.readPointer();
          ok = !actor.isNull() && v0.compare(base) >= 0 && v0.compare(base.add(mod.size)) < 0;
        } catch (e) {}
        out.push({id: id, ok: ok, v0: v0 ? off(v0) : null, actor: actor.toString()});
      }
      node = node.readPointer();
      guard++;
    }
  }
  return out;
}

let best = 0;
setInterval(function () {
  send({ev: 'tick', portrays: portrays, mgr: mgr ? mgr.toString() : null});
  if (mgr === null) return;
  try {
    const list = nodes();
    const real = (list || []).filter((x) => x.id !== '0');
    if (real.length > best) {
      best = real.length;
      const good = real.filter((x) => x.ok).length;
      send({ev: 'nodes', real: real.length, good: good, nodes: real});
    }
  } catch (e) { send({ev: 'nodes-err', err: String(e).slice(0, 120)}); }
}, 4000);
send({ev: 'ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] portrayal observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
