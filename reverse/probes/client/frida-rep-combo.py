#!/usr/bin/env python3
"""Combined REP hook: force gates + dump the V3 send buffer (Frida, OUR runtime).

1. Forces gate 1 (carrier IsConnected virtual, vtable slot 0xa8) to 1.
2. Logs gate 2 ([carrier+0xA0] via 0x145a92380).
3. Logs SendRegistrationRequestV3 calls (0x145a905d0).
4. Hooks the carrier send virtual (slot 0 of vtable at [obj+0xb0]) and dumps
   the buffer/length the client tries to send.
"""

from __future__ import annotations

import sys
import time

import frida

JS = r"""
const SET_STATE = ptr('0x14645FD70');
const READY_GETTER = ptr('0x145A92380');
const SEND_REG = ptr('0x145A905D0');

const base = Process.enumerateModules()[0].base;
const off = (va) => va.sub(0x140000000);
console.log('[*] base = ' + base);

let carrierObj = null;
let hooked = null;

Interceptor.attach(base.add(off(SEND_REG)), {
    onEnter(args) {
        const obj = args[0];
        console.log('[reg] CALLED obj=' + obj);
        try {
            const vt = obj.add(0xb0).readPointer();
            const fn = vt.readPointer();
            console.log('[reg] sendfn=' + fn);
            if (hooked === null || !hooked.equals(fn)) {
                hooked = fn;
                Interceptor.attach(fn, {
                    onEnter(a) {
                        try {
                            const rcx = a[0];
                            console.log('[send] rcx=' + rcx);
                            for (let i = 0; i < 6; i++) {
                                try {
                                    const p = rcx.add(i * 8).readPointer();
                                    const n = Number(p);
                                    if (n > 0x10000) {
                                        try {
                                            const head = p.readByteArray(32);
                                            let hex = '';
                                            const bytes = new Uint8Array(head);
                                            for (let b of bytes) hex += ('0' + b.toString(16)).slice(-2);
                                            console.log('[send] rcx+' + (i*8) + '=' + p + ' head=' + hex);
                                        } catch (e) {
                                            console.log('[send] rcx+' + (i*8) + '=' + p);
                                        }
                                    } else {
                                        console.log('[send] rcx+' + (i*8) + '=0x' + n.toString(16));
                                    }
                                } catch (e) {}
                            }
                        } catch (e) { console.log('[send] err ' + e); }
                    },
                    onLeave(r) { console.log('[send] ret=' + r); },
                });
                console.log('[send] hooked ' + fn);
            }
        } catch (e) { console.log('[reg] err ' + e); }
    },
});

Interceptor.attach(base.add(off(READY_GETTER)), {
    onEnter() {
        const carrier = this.context.rcx.sub(0x130);
        const ready = this.context.rcx.add(0xA0).readU32();
        if (carrierObj !== null && carrier.equals(carrierObj)) {
            console.log('[ready?] [+0xA0]=' + ready);
        }
    },
});

let isConnectedFn = null;
Interceptor.attach(base.add(off(SET_STATE)), {
    onEnter(args) {
        const wrapper = this.context.rcx;
        if (args[1].toInt32() !== 10 || isConnectedFn) return;
        carrierObj = wrapper.add(0x1000).readPointer();
        const vt = carrierObj.readPointer();
        isConnectedFn = vt.add(0xa8).readPointer();
        console.log('[fsm] carrier=' + carrierObj);
        Interceptor.attach(isConnectedFn, {
            onEnter() {
                this.mine = this.context.rcx.equals(carrierObj);
            },
            onLeave(ret) {
                if (this.mine && ret.toInt32() === 0) {
                    ret.replace(ptr(1));
                }
            },
        });
        console.log('[fsm] gate force ARMED');
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
    print("[*] armed — press JUGAR (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
