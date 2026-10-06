#!/usr/bin/env python3
"""Hardware watchpoint on [mgr+8] — who writes the local-player pointer?

Frida (our private runtime): resolve the manager via the singleton
0x141026080, place a write watchpoint on [mgr+8] and log every write
with a full stack trace. Definitive answer to "does anything ever create
the local player entity, and from where".
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const SINGLETON = base.add(0x141026080 - 0x140000000);
const INNER_GETTER = base.add(0x146800d10 - 0x140000000); // the gate getter
const off = (p) => 'nw+' + p.sub(base).toString(16);

let armed = false;

function armWatch(inner) {
  // [inner+8] = entity, [inner+0x10] = ready-holder
  const slot = inner.add(8);
  send({ev: 'watch-armed', inner: inner.toString(), slot: slot.toString()});
  MemoryAccessMonitor.enable([{base: slot, size: 8}], {
    onAccess: function (details) {
      send({
        ev: 'access',
        op: details.operation,
        from: details.from ? off(details.from) : null,
      });
      if (details.operation !== 'write') { return true; }
    }
  });
  armed = true;
}

const timer = setInterval(function () {
  if (armed) { return; }
  try {
    const mgr = new NativeFunction(SINGLETON, 'pointer', [])();
    if (mgr.isNull()) { return; }
    // The gate virtual (vtable+0x30) reads [mgr->inner+8] — grab the inner
    // object via the same path the FSM uses: call the getter thunk's target
    // logic manually: inner is NOT stored in the wrapper... resolve it by
    // hooking the getter once to capture rcx.
    const getter = new NativeFunction(
      base.add(0x146167340 - 0x140000000), 'pointer', ['pointer', 'pointer']
    );
  } catch (e) {}
}, 500);

// Simpler: hook the getter BODY at 0x146800d10 (it is NOT patched when
// spawn-gate uses the call-site NOP) and capture rcx = inner object.
const GETTER = base.add(0x146800d10 - 0x140000000);
Interceptor.attach(GETTER, {
  onEnter(args) {
    const inner = args[0];
    if (!armed && !inner.isNull()) {
      try {
        armWatch(inner);
      } catch (e) {
        send({ev: 'arm-error', err: String(e)});
      }
    }
    // log the inner state every call
    try {
      const ent = inner.add(8).readPointer();
      const readyPtr = inner.add(0x10).readPointer();
      const flag = readyPtr.isNull() ? null : readyPtr.readU8();
      send({ev: 'getter', inner: inner.toString(), entity: ent.toString(),
            readyPtr: readyPtr.toString(), flag: flag});
    } catch (e) {
      send({ev: 'getter-read-error', err: String(e)});
    }
  }
});
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)

    def on_msg(m, _d) -> None:
        payload = m.get("payload") or m
        print(payload, flush=True)

    script.on("message", on_msg)
    script.load()
    print("[probe] watchpoint armed when manager exists (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
