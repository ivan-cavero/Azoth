#!/usr/bin/env python3
"""Re-check whether the local player entity is created NOW that the world
stream actually flows.

The 2026-09-24 "never written" verdict was taken while the replay was being
truncated at 6370 B, so the replica layer never saw the world snapshot. The
VLQ fix changed that, so the verdict has to be re-tested before building on
it. Hooks the spawn-gate getter (FUN_146800d10) and reports, per call, the
entity pointer, the ready holder and the manager's session object, plus any
transition of [this+8] from null to non-null.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;

const GATE = base.add(rva(0x146800d10));
let lastEntity = '0x0';
let lastReady = '0x0';
let calls = 0;
let transitions = 0;

Interceptor.attach(GATE, {
  onEnter(args) {
    calls++;
    const inner = args[0];
    let ent = 'err', ready = 'err', flag = null;
    try {
      ent = inner.add(8).readPointer().toString();
      const rp = inner.add(0x10).readPointer();
      ready = rp.toString();
      if (!rp.isNull()) flag = rp.readU8();
    } catch (e) { ent = 'err:' + String(e); }
    if (ent !== lastEntity || ready !== lastReady) {
      transitions++;
      send({ev: 'transition', n: transitions, entity: ent, ready: ready,
            flag: flag, inner: inner.toString()});
      lastEntity = ent;
      lastReady = ready;
    }
  }
});

setInterval(function () {
  send({ev: 'state', calls: calls, entity: lastEntity, ready: lastReady,
        transitions: transitions});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] spawn-gate getter armed (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
