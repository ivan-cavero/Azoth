#!/usr/bin/env python3
"""Trace WHO calls the carrier send (Frida, OUR runtime).

The carrier send virtual (0x146441b40) is called with rcx = the message-port
object. We log its caller's return address and resolve which module/function
it belongs to, to find the V3 registration send path.
"""

from __future__ import annotations

import sys
import time

import frida

JS = r"""
const SEND = ptr('0x146441B40');

const base = Process.enumerateModules()[0].base;
const off = (va) => va.sub(0x140000000);
console.log('[*] base = ' + base);

Interceptor.attach(base.add(off(SEND)), {
    onEnter() {
        const ret = this.context.rsp.readPointer().sub(base);
        console.log('[send] called from +0x' + ret.toString(16));
    },
});
"""


def main() -> int:
    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        print("NewWorld.exe not running")
        return 1
    script = session.create_script(JS)
    script.on("message", lambda m, d: print(m.get("payload") or m))
    script.load()
    print("[*] tracing send callers — press JUGAR (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
