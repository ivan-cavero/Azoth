#!/usr/bin/env python3
"""Watch the post-transition activation: what happens right after 13->14.

The case-0xd tail (decomp): after the FSM sets state 0xe it calls
  plVar10 = *(this + 0x48); if (plVar10) (**(*plVar10 + 0x20))(plVar10, this+0x1040)
That call is what should hand the connection to the replica layer.
Hook it live: is [this+0x48] NULL? Is the virtual called?
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const off = (p) => 'nw+' + p.sub(base).toString(16);

// The case-0xd block: lea rcx,[rbx+0x130]; call getter; ... transition.
// After 'mov dword ptr [rbx + 0x1530], 0xe' comes the activation. From
// the 0x14644a8bd disasm, the transition site ends at ~0x14644a95a.
// Hook the instruction after the state store: 0x14644a952 (lea rcx,[rbp+0x30]
// at a952) is post-transition; instead hook the state STORE itself and
// then inspect [rbx+0x48] on a timer.
const STATE_STORE = base.add(0x14644a948 - 0x140000000); // mov [rbx+0x1530], 0xe

Interceptor.attach(base.add(0x14644a8c4 - 0x140000000), {
  // the getter call in case 0xd — fires each frame while in state 13
  onLeave(ret) {
    this.rbx = this.context.rbx;
  }
});

// Poll for state==0xe and inspect [rbx+0x48] via the known GameConnection.
// We need the GameConnection pointer: capture it from the case-0xd frame.
let gc = null;
let hooked = false;
Interceptor.attach(base.add(0x14644a8bd - 0x140000000), {
  onEnter() {
    if (!gc) {
      gc = this.context.rbx;
      send({ev: 'gc-found', addr: gc.toString(), state: gc.add(0x1530).readS32()});
    }
  }
});

setInterval(function () {
  if (!gc || hooked) return;
  try {
    const state = gc.add(0x1530).readS32();
    if (state !== 14) return;
    const vt = gc.add(0x48).readPointer();
    const fn = vt.add(0x20).readPointer();
    send({ev: 'activation-vt', vt: off(vt), fn: off(fn)});
    Interceptor.attach(fn, {
      onEnter(args) {
        send({ev: 'activation-called', thisArg: this.context.rcx.toString(),
              arg2: args[1] ? args[1].toString() : null});
      }
    });
    hooked = true;
  } catch (e) {
    send({ev: 'tick-error', err: String(e)});
  }
}, 500);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] watching post-transition activation (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
