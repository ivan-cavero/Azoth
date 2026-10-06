#!/usr/bin/env python3
"""Probe the REAL typed-stream pump (FUN_146b085d0) and its success store.

Earlier probes hooked 0x146b08500, a 7-byte helper -- not the pump. The
actual pump starts at 0x146b085d0 and calls the envelope unmarshal
FUN_1461ac8d0. Its structure:

    msg = pop(global_queue)
    if (read([param_1+0x58]) != 0):        <-- schema/type context gate
        copy [param_1+0x58] -> auStack_a0
        FUN_1461ac8d0(..., auStack_a0, ...)  <-- envelope unmarshal
        if (parse_ok && non_empty(auStack_a0)):
            ... logging ...
        else:
            [param_1+0x80] = *lookup(msg)    <-- SUCCESS store @0x146b08715
    return

So three counters decide everything:
  * pump calls
  * gate open ([param_1+0x58] non-null)
  * success store hits (0x146b08715)
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const off = (p) => 'nw+' + p.sub(base).toString(16);

const PUMP    = base.add(0x146b085d0 - 0x140000000);
const UNMARSH = base.add(0x1461ac8d0 - 0x140000000);
const SUCCESS = base.add(0x146b08715 - 0x140000000);

let c = {pump: 0, gateOpen: 0, gateClosed: 0, unmarshal: 0, ok: 0, fail: 0};
let firstPump = true;
let failCodes = {};

Interceptor.attach(PUMP, {
  onEnter(args) {
    c.pump++;
    const self = args[0];
    let ctx = 'n/a';
    let has = false;
    try {
      const p = self.add(0x58).readPointer();
      has = !p.isNull();
      ctx = off(p);
    } catch (e) { ctx = 'err:' + String(e); }
    if (has) c.gateOpen++; else c.gateClosed++;
    if (firstPump) {
      firstPump = false;
      send({ev: 'first-pump', self: self.toString(), ctx58: ctx});
    }
  }
});

Interceptor.attach(UNMARSH, {
  onEnter(args) {
    c.unmarshal++;
    this.out = args[1];
  },
  onLeave() {
    // param_2 = [code:u8][ok:u8]. ok==1 -> success store at [this+0x80].
    let code = -1, ok = 0;
    try {
      code = this.out.readU8();
      ok = this.out.add(1).readU8();
    } catch (e) {}
    if (ok) { c.ok++; }
    else {
      c.fail++;
      const k = 'code=' + code;
      failCodes[k] = (failCodes[k] || 0) + 1;
    }
  }
});

// Hook the instruction that stores on the success path by hooking the
// containing instruction's basic block via the nearest function-safe point:
// Interceptor.attach at SUCCESS patches the instruction, so instead watch
// the write target through onEnter of the NEXT call (0x140876b20 is the
// string emptiness probe that gates the success branch). Simpler: count
// [param_1+0x80] transitions from the pump hook.
setInterval(function () {
  send({ev: 'counts', ...c, failCodes: failCodes});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] real pump @146b085d0 armed (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
