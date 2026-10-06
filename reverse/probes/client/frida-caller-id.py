#!/usr/bin/env python3
"""Identify the real typed-stream caller by capturing return addresses.

Static xrefs gave three callers of the envelope unmarshal
FUN_1461ac8d0 (0x146a6ec17 / 0x146b086f2 / 0x146b6ec5f), but two of their
containing functions report 0 live calls, so the hot path was mislabelled
twice already. Instead of guessing again, capture `returnAddress` at
runtime: the actual call site tells us which layer is alive, and the
`self` argument tells us the session object so we can read the type id.

Also records the envelope's type id from `*param_3` (the pump passes
`&flags|type`) for every message the client actually parsed, so the 1.365
replay ids can be compared against what this 1.400 build dispatches.
"""

from __future__ import annotations

import time
from collections import Counter

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const off = (p) => {
  const d = p.sub(base);
  // A negative offset means the pointer is outside the module; print raw.
  return (d.compare(ptr(0)) < 0) ? p.toString() : 'nw+' + d.toString(16);
};

const UNMARSH = base.add(rva(0x1461ac8d0));

let callers = {};
let types = [];
let n = 0;

Interceptor.attach(UNMARSH, {
  onEnter(args) {
    n++;
    const ret = this.returnAddress;
    const key = off(ret);
    callers[key] = (callers[key] || 0) + 1;
    // args[2] = param_3 = uint* with the record header; read a few words so
    // we can see the shape the client parsed.
    let hdr = null;
    try {
      hdr = [0, 4, 8].map((o) => '0x' + args[2].add(o).readU32().toString(16));
    } catch (e) { hdr = ['err', String(e)]; }
    let self = null;
    try { self = args[2].readPointer().toString(); } catch (e) {}
    if (n <= 12) send({ev: 'call', n: n, caller: key, hdr: hdr, self: self});
  },
  onLeave() {}
});

setInterval(function () {
  send({ev: 'summary', total: n, callers: callers});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] capturing real unmarshal callers (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
