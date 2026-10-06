#!/usr/bin/env python3
"""Dump live memory around the 13->14 gate: singleton, vtable, fn bytes.

Reads (Frida, our private runtime only):
  - singleton 0x141026080 return value (manager object)
  - [mgr+0] first pointer ("vtable" candidate)
  - [vt+0x30] the virtual the FSM calls (RVA 0x6800d10 last run)
  - 96 bytes of fn for offline capstone
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const SINGLETON = base.add(0x141026080 - 0x140000000);
let done = false;
Interceptor.attach(SINGLETON, {
  onLeave(retval) {
    if (done) return;
    done = true;
    const mgr = retval;
    const vt = mgr.readPointer();
    const fn = vt.add(0x30).readPointer();
    const fnBytes = fn.readByteArray(96);
    const vtBytes = vt.readByteArray(0x40);
    send({ev: 'meta', mgr: mgr.toString(), vt: vt.toString(), fn: fn.toString(),
          fnRva: fn.sub(base).toString(16)});
    send({fn: fnBytes}, fnBytes);
    send({vt: vtBytes}, vtBytes);
  }
});
send({ev: 'ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)

    def on_msg(m, data) -> None:
        payload = m.get("payload") or m
        if data:
            raw = bytes(data)
            name = "fn" if "fn" in payload else "vt"
            for i in range(0, len(raw), 32):
                print(f"{name}+{i:03x}: {raw[i:i+32].hex()}")
        else:
            print(payload, flush=True)

    script.on("message", on_msg)
    script.load()
    for _ in range(50):
        time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
