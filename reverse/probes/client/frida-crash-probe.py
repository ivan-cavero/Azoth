#!/usr/bin/env python3
"""Inspect the post-V3 SelfIdent spawn crash (Frida, OUR runtime).

Hooks the SelfIdent handler (FUN_146454c00) and the crash site
(FUN_146b6f190), dumping the objects involved, and installs an
exception handler so the AV is reported instead of killing the process.

Usage: python reverse/probes/client/frida-crash-probe.py --seconds 120
"""

from __future__ import annotations

import argparse
import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { throw new Error('no NewWorld.exe'); }
const base = mod.base;
const off = (va) => base.add(va - 0x140000000);

const SELFIDENT = off(0x146454c00);
const CRASHSITE = off(0x146b6f190);

Process.setExceptionHandler(function (details) {
  send({ev: 'exception', type: details.type,
        addr: String(details.address),
        context: { rip: String(details.context.rip),
                   rax: String(details.context.rax),
                   rcx: String(details.context.rcx),
                   rdx: String(details.context.rdx) }});
  return false;  // let it crash
});

Interceptor.attach(SELFIDENT, {
  onEnter(args) {
    const p6 = args[5];
    let f0 = null, dbg = null, f2c = null, f34 = null;
    try {
      f0 = p6.readU32();
      dbg = p6.add(0x28).readU8();
      f2c = p6.add(0x2c).readU64();
      f34 = p6.add(0x34).readU32();
    } catch (e) { f0 = 'err'; }
    send({ev: 'selfident', p6: String(p6), field0: f0, debug: dbg,
          field2c: String(f2c), field34: f34,
          p3: String(args[2]), p4: String(args[3]), p5: String(args[4]),
          p7: String(args[6])});
  }
});

Interceptor.attach(CRASHSITE, {
  onEnter(args) {
    const p2 = args[1];
    let obj = null, vt = null, vt30 = null;
    try {
      obj = p2.readPointer();
      vt = obj.readPointer();
      vt30 = vt.add(0x30).readPointer();
    } catch (e) { obj = 'err:' + e; }
    send({ev: 'crashsite', p1: String(args[0]), p2: String(p2),
          obj: String(obj), vt: String(vt), vt30: String(vt30)});
  }
});
send({ev: 'ready', base: String(base)});
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120)
    args = ap.parse_args()

    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)

    def on_message(msg, data):
        if msg.get("type") == "send":
            print("[crash]", msg["payload"], flush=True)
        else:
            print("[crash]", msg, flush=True)

    script.on("message", on_message)
    script.load()
    print("[crash] loaded", flush=True)
    time.sleep(args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())