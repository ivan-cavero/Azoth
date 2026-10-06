#!/usr/bin/env python3
"""Trace the client's REP connection state machine live (Frida, OUR runtime).

From the static analysis (research/docs/REP-PROTOCOL.md):
- 0x14645fd70: GameConnection::SetState(edx = new state) — logs the ladder.
- 0x145a905d0: likely SendRegistrationRequest (called from the
  WaitingForREPConnection case when carrier->IsConnected() and rep.ready==0).
- The WaitingForREPConnection case gates on a virtual call at
  [wrapper+0x1000] vtable slot 0xa8 — we resolve it at runtime and log
  every return value.

Usage: python reverse/probes/client/frida-rep-fsm.py
"""

from __future__ import annotations

import sys
import time

import frida

JS = r"""
const SET_STATE = ptr('0x14645FD70');
const SEND_REG = ptr('0x145A905D0');

const base = Process.enumerateModules()[0].base;
const off = (va) => va.sub(0x140000000);
console.log('[*] base = ' + base);

let regHooked = false;
let isConnectedFn = null;

Interceptor.attach(base.add(off(SET_STATE)), {
    onEnter(args) {
        const wrapper = this.context.rcx;
        const newState = args[1].toInt32();
        console.log('[state] wrapper=' + wrapper + ' -> ' + newState);
        if (newState === 10 && !isConnectedFn) {
            const carrier = wrapper.add(0x1000).readPointer();
            const vt = carrier.readPointer();
            isConnectedFn = vt.add(0xa8).readPointer();
            console.log('[fsm] carrier=' + carrier + ' IsConnected?=' + isConnectedFn);
            Interceptor.attach(isConnectedFn, {
                onLeave(ret) {
                    console.log('[IsConnected] -> ' + ret.toInt32());
                },
            });
        }
    },
});

Interceptor.attach(base.add(off(SEND_REG)), {
    onEnter() {
        console.log('[reg] SendRegistrationRequest CALLED');
        regHooked = true;
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
