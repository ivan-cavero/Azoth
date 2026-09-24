#!/usr/bin/env python3
"""Catch the code that WRITES the local player's entity id ([mgr+8]).

Facts established 2026-09-24:
  * `this+8` is NOT a pointer, it is the local player's entity id.
    FUN_146801040 (mgr vtable slot 0x78) requires `this+8 != 0` and
    `*(*(this+0x10)) != 0`, then looks `this+8` up in a hash table at
    `this+0x110` to obtain the actor.
  * The spawn gate 0x146800d10 (vtable slot 0x30) applies the same two
    conditions; it is NOPed at the call site so the FSM advances anyway.
  * Every vtable slot is a getter -- there is no virtual setter, so the
    id is written by ordinary code.

This probe arms MemoryAccessMonitor on `[mgr+8]` (8 bytes) using the
manager pointer captured from the gate itself, so the earlier mistake of
watching the singleton wrapper's object does not repeat. Any write is
reported with its originating code address.
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
let armed = false;
let writes = 0;

function arm() {
  if (armed || mgr === null) return;
  const slot = mgr.add(8);
  armed = true;
  send({ev: 'armed', mgr: mgr.toString(), slot: slot.toString(),
        current: slot.readU64().toString()});
  try {
    MemoryAccessMonitor.enable([{ base: slot, size: 8 }], {
      onAccess: function (details) {
        if (details.operation === 'write') {
          writes++;
          send({ev: 'WRITE', from: details.from ? off(details.from) : '?',
                value: mgr.add(8).readU64().toString(), n: writes});
        } else {
          send({ev: 'read', from: details.from ? off(details.from) : '?'});
        }
        return true;  // keep monitoring
      }
    });
  } catch (e) {
    send({ev: 'arm-error', err: String(e)});
  }
}

Interceptor.attach(GATE, {
  onEnter(args) {
    if (mgr === null) {
      mgr = args[0];
      send({ev: 'mgr-found', mgr: mgr.toString()});
      arm();
    }
  }
});

setInterval(function () {
  if (mgr === null) { send({ev: 'waiting'}); return; }
  send({ev: 'state', id: mgr.add(8).readU64().toString(),
        readyPtr: mgr.add(0x10).readPointer().toString(), writes: writes});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] watching local-player entity id (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
