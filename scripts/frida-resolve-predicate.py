#!/usr/bin/env python3
"""One-shot: resolve [pGame+0x28]->vtable[0x88] and report the RVA.

Attaches, reads the globals, prints what it finds (including the failure
reason at every step), and detaches. No world attempt required.

    python scripts/frida-resolve-predicate.py
"""

from __future__ import annotations

import json
import sys
import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (p) => '0x' + p.sub(base).toString(16);
const at = (va) => base.add(va - 0x140000000);

const out = {module_base: base.toString(), steps: []};

function tryRead(label, addr, size) {
  try {
    const p = addr.readPointer();
    out.steps.push({label, addr: addr.toString(), addr_rva: rva(addr),
                    value: p.toString(), value_rva: rva(p)});
    return p;
  } catch (e) {
    out.steps.push({label, addr: addr.toString(), addr_rva: rva(addr),
                    error: String(e)});
    return null;
  }
}

// The decompiled form is: pGame = *(DAT_14a7ba0e0 + 0x60)
const GLOB = at(0x14A7BA0E0);
out.glob = GLOB.toString();
const pGame = tryRead('*(global+0x60)', GLOB.add(0x60));
if (pGame && !pGame.isNull()) {
  const mgr = tryRead('pGame+0x28', pGame.add(0x28));
  if (mgr && !mgr.isNull()) {
    const vt = tryRead('mgr->vtable', mgr);
    if (vt && !vt.isNull()) {
      const fn = tryRead('vtable[0x88]', vt.add(0x88));
      if (fn && !fn.isNull()) {
        out.predicate_rva = rva(fn);
        out.predicate = fn.toString();
        try {
          out.prologue = Array.from(new Uint8Array(fn.readByteArray(24)))
            .map((b) => b.toString(16).padStart(2, '0')).join(' ');
        } catch (e) { out.prologue = 'read-error: ' + e; }
      }
    }
  }
}
send(out);
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    result: list = []
    script = session.create_script(JS)
    script.on("message", lambda m, _d: result.append(m.get("payload") or m))
    script.load()
    for _ in range(30):
        if result:
            break
        time.sleep(0.2)
    print(json.dumps(result, indent=1) if result else "no result")
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
