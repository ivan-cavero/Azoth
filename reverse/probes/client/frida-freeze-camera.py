#!/usr/bin/env python3
"""Keep the first world-space camera matrix.

The level draws during load, then the view clears because the player pawn
was never constructed. FUN_145f62e80 writes a 4x4 matrix at this+0x90 from
the live camera. Once that matrix contains a world-scale translation, later
calls are overwritten with the saved matrix so the view stays where the
load camera was.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
let saved = null;
let logs = 0;

function floats(p, n) {
  const out = [];
  for (let i = 0; i < n; i++) out.push(p.add(i * 4).readFloat());
  return out;
}

function worldy(f) {
  let n = 0;
  for (const x of f) if (Math.abs(x) > 800 && Math.abs(x) < 200000) n++;
  return n >= 2;
}

Interceptor.attach(at(0x145f62e80), {
  onEnter(args) { this.self = args[0]; },
  onLeave() {
    const m = this.self.add(0x90);
    let f;
    try { f = floats(m, 16); } catch (e) { return; }
    if (saved === null) {
      if (logs < 8 || worldy(f)) {
        logs++;
        send({ev: 'cam', f: f.map(x => Math.abs(x) > 100 ? x.toFixed(0) : x.toFixed(2))});
      }
      if (worldy(f)) {
        saved = f;
        send({ev: 'FROZE'});
      }
      return;
    }
    for (let i = 0; i < 16; i++) m.add(i * 4).writeFloat(saved[i]);
  }
});
send({ev: 'ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] camera freeze armed", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
