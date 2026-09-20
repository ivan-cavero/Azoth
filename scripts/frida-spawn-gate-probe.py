#!/usr/bin/env python3
"""Probe the 13->14 spawn gate live (Frida, our private runtime only).

The GameConnection FSM block at 0x14644a8bd transitions to state 14 when:
  1. [carrier+0x252] player-spawn getter (0x145a923c0) != 0  (forced 1)
  2. singleton 0x141026080 != NULL                            (lazy init)
  3. that singleton's vtable+0x30 (...) != NULL               <-- unknown

Hook the call site and resolve the virtual target at runtime; log every
evaluation plus which gate fails. Run while the client sits in
WaitingForPlayerSpawn (after clicking JUGAR).
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const SITE = base.add(0x14644a8bd - 0x140000000);   // lea rcx,[rbx+0x130]
const GATE1 = base.add(0x145a923c0 - 0x140000000);  // player-spawn getter
const SINGLETON = base.add(0x141026080 - 0x140000000);
const STATE = 0x1530; // [rbx+STATE] = current FSM state

let virtTarget = null;

// NOTE: do NOT hook 0x145a923c0 — the ladder patch made it `mov al,1; ret`
// (3 bytes: Interceptor cannot attach, live error 2026-09-19).

Interceptor.attach(SITE, {
  onEnter() {
    this.rbx = this.context.rbx;
    send({ev: 'site', state: this.rbx.add(STATE).readS32()});
  }
});

Interceptor.attach(SINGLETON, {
  onLeave(retval) {
    const mgr = retval;
    if (mgr.isNull()) { send({ev: 'singleton', ret: 'NULL'}); return; }
    try {
      const vt = mgr.readPointer();
      const fn = vt.add(0x30).readPointer();
      if (!virtTarget || !fn.equals(virtTarget)) {
        virtTarget = fn;
        send({ev: 'vtable-resolved', mgr: mgr.toString(), fn: fn.toString(),
              off: fn.sub(mod.base).toString(16)});
        Interceptor.attach(fn, {
          onLeave(r) { send({ev: 'gate3-virtual', ret: r.toString()}); }
        });
      }
    } catch (e) { send({ev: 'vtable-error', err: String(e)}); }
  }
});
send({ev: 'ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] attached — click JUGAR in the game now (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
