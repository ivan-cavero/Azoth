#!/usr/bin/env python3
"""Live-probe the spawn manager during InGame (Frida, our runtime only).

Polls the manager from singleton 0x141026080:
  [mgr+8]   local player entity pointer (the 13->14 gate value)
  [mgr+0x10] pointer whose [0] byte must be non-zero (ready flag)
Logs every transition so we can see whether ANYTHING ever writes them,
and dumps the vtable + object graph when the entity appears.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const SINGLETON = base.add(0x141026080 - 0x140000000);
const off = (p) => p.sub(base).toString(16);

let lastEntity = '0x0';
let lastReady = '0x0';
let reported = false;

const timer = setInterval(function () {
  const mgr = new NativeFunction(SINGLETON, 'pointer', [])();
  if (mgr.isNull()) { return; }
  const ent = mgr.add(8).readPointer();
  const ready = mgr.add(0x10).readPointer();
  const entS = ent.toString();
  const readyS = ready.toString();
  if (entS !== lastEntity) {
    send({ev: 'entity-change', from: lastEntity, to: entS, rva: ent.isNull() ? null : off(ent)});
    lastEntity = entS;
  }
  if (readyS !== lastReady) {
    let flag = null;
    try { flag = ready.readU8(); } catch (e) {}
    send({ev: 'ready-change', from: lastReady, to: readyS, flag: flag});
    lastReady = readyS;
  }
}, 200);

send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] polling manager — click JUGAR now (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
