#!/usr/bin/env python3
"""Force BOTH gates of the WaitingForREPConnection case (Frida, OUR runtime).

Decompiled case at 0x14644a6c1 (see research/docs/REP-PROTOCOL.md):

    if (carrier->IsConnected()) {          // vtable slot 0xa8
        if ([carrier+0xA0] == 0) {         // rep.ready via 0x145a92380
            SendRegistrationRequestV3();   // 0x145a905d0
        }
        advance_to_state_11();
    }

Gate 1 alone (forced since 2026-09-16) reaches state 11 but the client never
sends the V3 registration. This forces gate 1 AND logs gate 2's value; if
[carrier+0xA0] != 0 we also patch it to 0 so the send path is reached.
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

Interceptor.attach(base.add(off(SEND_REG)), {
    onEnter() { console.log('[reg] SendRegistrationRequestV3 CALLED'); },
});

Interceptor.attach(base.add(off(READY_GETTER)), {
    onEnter() {
        const carrier = this.context.rcx.sub(0x130);
        const ready = this.context.rcx.add(0xA0).readU32();
        const mine = carrierObj !== null && carrier.equals(carrierObj);
        console.log('[ready?] carrier=' + carrier + ' [+0xA0]=' + ready + (mine ? ' (OURS)' : ''));
        if (mine && ready !== 0) {
            this.context.rcx.add(0xA0).writeU32(0);
            console.log('[ready?] patched to 0');
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
        console.log('[fsm] carrier=' + carrierObj + ' gate=' + isConnectedFn);
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
        console.log('[fsm] gate-1 force ARMED');
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
