#!/usr/bin/env python3
"""Force the ClientSDK EOS skip (FUN_1444f5700).

At 0x1444f5700 the client does:

    global = *0x14a79a0e0
    if (global && (global[0x244] || global[0x245] || global[0x246])) {
        this[0x130] = 1;   // skip EOS entirely
        return;
    }
    if (!resolve_eos_exports()) { log [ERROR]; this[0x130] = 1; return; }
    // else BeginSession / AddNotify ...

Our export stubs still left them failing in 48ms (Game.log 18:48:53).
This patch takes THEIR skip path: `this[0x130]=1; return`.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { throw new Error('no module'); }
const base = mod.base;
const addr = base.add(ptr('0x1444F5700').sub(ptr('0x140000000')));
const before = new Uint8Array(addr.readByteArray(12));
let h=[]; for (let i=0;i<12;i++) h.push(('0'+before[i].toString(16)).slice(-2));
send({before: h.join(' ')});

// mov byte ptr [rcx+0x130], 1 ; mov al, 1 ; ret
const want = [0xC6, 0x81, 0x30, 0x01, 0x00, 0x00, 0x01, 0xB0, 0x01, 0xC3];
Memory.patchCode(addr, want.length, function (code) {
  for (let i = 0; i < want.length; i++) code.add(i).writeU8(want[i]);
});
const after = new Uint8Array(addr.readByteArray(want.length));
h=[]; for (let i=0;i<want.length;i++) h.push(('0'+after[i].toString(16)).slice(-2));
send({after: h.join(' '), ok: true});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    got: list = []
    script = session.create_script(JS)
    script.on("message", lambda m, _d: got.append(m.get("payload") or m))
    script.load()
    for _ in range(20):
        if any(isinstance(x, dict) and x.get("ok") for x in got):
            break
        time.sleep(0.1)
    print(got)
    session.detach()
    print("[azoth] FUN_1444f5700 patched to skip EOS; click Jugar")
    return 0 if any(isinstance(x, dict) and x.get("ok") for x in got) else 1


if __name__ == "__main__":
    raise SystemExit(main())
