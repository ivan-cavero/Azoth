#!/usr/bin/env python3
"""Dump the V3 registration buffer at the carrier send (Frida, OUR runtime).

The send path is: 0x145a905d0 stores carrier at [obj+0xa8], calls virtual
[obj+0xb0] slot 0 (= 0x146441b40), which eventually sends. We hook the slot-0
target and dump rcx+0x10 (buffer) / rcx+0x18 (length) if present, else dump
rcx itself. One JUGAR press shows us the exact bytes the client would send.
"""

from __future__ import annotations

import sys
import time

import frida

JS = r"""
const SEND_REG = ptr('0x145A905D0');

const base = Process.enumerateModules()[0].base;
const off = (va) => va.sub(0x140000000);
console.log('[*] base = ' + base);

let hooked = null;
Interceptor.attach(base.add(off(SEND_REG)), {
    onEnter(args) {
        const obj = args[0];
        const vt = obj.add(0xb0).readPointer();
        const fn = vt.readPointer();
        console.log('[reg] obj=' + obj + ' sendfn=' + fn);
        if (hooked === null || !hooked.equals(fn)) {
            hooked = fn;
            Interceptor.attach(fn, {
                onEnter(a) {
                    try {
                        const rcx = a[0];
                        console.log('[send] rcx=' + rcx);
                        for (let i = 0; i < 4; i++) {
                            try {
                                const p = rcx.add(i * 8).readPointer();
                                console.log('[send] rcx+' + (i*8) + ' ptr=' + p);
                            } catch (e) {}
                        }
                        // try reading as buffer directly
                        try {
                            const b = rcx.readByteArray(64);
                            console.log('[send] rcx-bytes: ' + b);
                        } catch (e) {}
                    } catch (e) { console.log('[send] err ' + e); }
                },
            });
            console.log('[send] hooked ' + fn);
        }
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
    print("[*] tracing — press JUGAR (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
