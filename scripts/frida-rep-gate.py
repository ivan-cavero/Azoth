#!/usr/bin/env python3
"""Watch the REP connect gate live (Frida, OUR private runtime only).

The GameConnection FSM (WaitingForREPConnection case, 0x14644a6c1) only
proceeds when `[carrier + 0xE0] == 2` (getter 0x145a923a0). This script:

1. logs every gate call with the current value of [rcx+0xE0],
2. watches writes to that exact object field (MemoryAccessMonitor)
   so we learn WHO sets it and to what,
3. traces the ActorContainerConnect entry (0x146420460).

Usage:
  python scripts/frida-rep-gate.py            # attach to running NewWorld.exe
"""

from __future__ import annotations

import sys
import time

import frida

GATE_GETTER = 0x145A923A0  # cmp dword [rcx+0xE0], 2; sete al
FSM_GATE_RET = 0x14644A6D1  # return address of the FSM's call
ACTOR_CONNECT = 0x146420460  # CGame::ActorContainerConnect

JS = r"""
const GATE = ptr('0x145A923A0');
const FSM_CASE = ptr('0x14644A6C1'); // WaitingForREPConnection case start
const FSM_AFTER_CALL = ptr('0x14644A6D1'); // test al,al — rbx = wrapper
const CARRIER_READY_GETTER = ptr('0x145A92380');

const mod = Process.enumerateModules()[0];
const base = mod.base;
const off = (va) => va.sub(0x140000000);
console.log('[*] base = ' + base);

let carrierObj = null;
let wrapperObj = null;

// Fire when the FSM reaches the WaitingForREPConnection case.
Interceptor.attach(base.add(off(FSM_AFTER_CALL)), {
    onEnter() {
        const wrapper = this.context.rbx;
        if (wrapper.isNull() || wrapper.equals(wrapperObj)) return;
        wrapperObj = wrapper;
        const carrier = wrapper.add(0x1000).readPointer();
        carrierObj = carrier;
        const vt = carrier.readPointer();
        const getter = vt.add(0xa8).readPointer();
        console.log('[fsm] wrapper=' + wrapper + ' carrier=' + carrier +
            ' vtable=' + vt + ' slot[0xa8]=' + getter +
            ' [+0xE0]=' + carrier.add(0xE0).readU32() +
            ' [+0x130+0xA0]=' + carrier.add(0x130 + 0xA0).readU32());
        globalThis.carrierReady = true;
    },
});

// Log every call to the rep.ready getter with its object.
Interceptor.attach(base.add(off(CARRIER_READY_GETTER)), {
    onEnter() {
        const o = this.context.rcx;
        const base0 = o.sub(0x130);
        console.log('[ready?] obj=' + base0 + ' [+0xA0]=' +
            o.add(0xA0).readU32());
    },
});

setInterval(() => {
    if (carrierObj && !globalThis.watching) {
        globalThis.watching = true;
        try {
            MemoryAccessMonitor.enable(
                [{ base: carrierObj.add(0xE0), size: 4 }],
                {
                    onAccess(details) {
                        console.log('[watch] ' + details.operation +
                            ' @' + details.from + ' -> [+0xE0]=' +
                            carrierObj.add(0xE0).readU32());
                    },
                }
            );
            console.log('[watch] monitoring [carrier+0xE0] at ' + carrierObj);
        } catch (e) {
            console.log('[watch] failed: ' + e);
        }
    }
}, 1000);
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
    print("[*] watching — now press JUGAR in the game (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
