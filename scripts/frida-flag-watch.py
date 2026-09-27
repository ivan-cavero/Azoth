#!/usr/bin/env python3
"""Read [mgr+0x3ac] at decision time and catch its writer.

The predicate installed in vtable slot 0x88 of the level streaming manager
is a one-byte getter (RVA 0x1038250):

    141038250  movzx eax, byte ptr [rcx + 0x3ac]
    141038257  ret

`LoadContextAndLevel` calls it twice; when the SECOND call returns non-zero
it takes the failure branch (`ctx+0x1a2 = 1` -> `Cleanup()`), and every later
state bundle is dropped with `clientContext == nullptr` — no local player
actor, black screen.

This probe does NOT guess the manager address: it hooks the predicate and
reads the byte from the receiver in `rcx`, so the object is always the exact
one being evaluated. On the first call it arms a write watch on that byte
and reports the writer with a backtrace.

Nothing is written to the process. Private runtime only (no EAC).
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
const rva = (p) => { try { return 'NewWorld+' + p.sub(base).toString(16); }
                     catch (e) { return '?'; } };

const PRED = at(0x141038250);

let calls = 0;
let armed = false;

Interceptor.attach(PRED, {
  onEnter(args) {
    calls++;
    const obj = args[0];
    let v = null;
    try { v = obj.add(0x3ac).readU8(); } catch (e) { v = 'err:' + e; }
    send({ev: 'predicate-enter', n: calls, obj: obj.toString(), value: v,
          obj_rva: rva(obj)});

    if (!armed && v === 0 || !armed) {
      armed = true;
      const field = obj.add(0x3ac);
      send({ev: 'arming-watch', field: field.toString()});
      try {
        MemoryAccessMonitor.enable({base: field, size: 1}, {
          onAccess(details) {
            if (!details.address.equals(field) || details.operation !== 'write') return;
            let frames = [];
            try {
              frames = Thread.backtrace(this.context, Backtracer.ACCURATE)
                .slice(0, 8).map((a) => rva(a));
            } catch (e) { frames = ['err ' + e]; }
            send({ev: 'WRITE', from: details.from.toString(),
                  from_rva: rva(details.from), frames: frames});
          }
        });
        send({ev: 'watch-armed'});
      } catch (e) {
        send({ev: 'watch-error', error: String(e)});
      }
    }
  },
  onLeave(ret) {
    send({ev: 'predicate-return', n: calls, value: ret.toInt32()});
  }
});

send({ev: 'ready', pred: PRED.toString()});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] predicate value+writer watcher active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
