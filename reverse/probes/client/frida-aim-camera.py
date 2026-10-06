#!/usr/bin/env python3
"""Point the live camera at the first real world actor.

Camera position lives at +0x54/+0x64/+0x74 on the object returned by
global 0x14a7ba0e0 -> +0x88 -> vtable+0x318. Actor translation is the
4th column of the 3x4 at actor+0x140. Rewritten every tick so the
follow-cam cannot pull it back to the missing player.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
let mgr = null;
let aimed = false;

Interceptor.attach(at(0x146800d10), {
  onEnter(args) { if (mgr === null) mgr = args[0]; }
});

function camera() {
  const g = at(0x14a7ba0e0).readPointer();
  const sys = g.add(0x88).readPointer();
  const fn = sys.readPointer().add(0x318).readPointer();
  const F = new NativeFunction(fn, 'pointer', ['pointer'], 'win64');
  return F(sys);
}

function firstActor() {
  if (mgr === null) return null;
  const cells = mgr.add(0x110).readPointer();
  const n = Number(mgr.add(0x108).readU64()) + 1;
  const seen = new Set();
  for (let i = 0; i < n; i++) {
    let node = cells.add(i * 0x10).add(8).readPointer();
    let g = 0;
    while (!node.isNull() && g < 400) {
      const k = node.toString();
      if (!seen.has(k)) {
        seen.add(k);
        const actor = node.add(0x28).readPointer();
        let ok = false;
        try {
          const v = actor.readPointer();
          ok = v.compare(base) >= 0 && v.compare(base.add(mod.size)) < 0;
        } catch (e) {}
        if (ok) {
          return {
            x: actor.add(0x14c).readFloat(),
            y: actor.add(0x15c).readFloat(),
            z: actor.add(0x16c).readFloat(),
          };
        }
      }
      node = node.readPointer();
      g++;
    }
  }
  return null;
}

function aim(cam, pos) {
  // Stand a few metres off the actor so we are not inside the mesh.
  cam.add(0x54).writeFloat(pos.x + 8);
  cam.add(0x64).writeFloat(pos.y - 12);
  cam.add(0x74).writeFloat(pos.z + 4);
}

setInterval(function () {
  let pos = null;
  try { pos = firstActor(); } catch (e) { send({ev:'walk', err:String(e).slice(0,80)}); return; }
  if (!pos) { send({ev:'no-actor', mgr: mgr ? mgr.toString() : null}); return; }
  let cam;
  try { cam = camera(); } catch (e) { send({ev:'nocam', err:String(e).slice(0,80)}); return; }
  aim(cam, pos);
  if (!aimed) {
    aimed = true;
    send({ev:'AIMED', pos: pos, cam: cam.toString()});
  }
}, 500);

// Re-apply at the start of the matrix rebuild so this frame uses our position.
Interceptor.attach(at(0x145f62e80), {
  onEnter() {
    if (!aimed) return;
    try {
      const pos = firstActor();
      if (pos) aim(camera(), pos);
    } catch (e) {}
  }
});
send({ev:'ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] camera aim armed", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
