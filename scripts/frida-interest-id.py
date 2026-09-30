#!/usr/bin/env python3
"""What interestId does the replay carry? — Frida probe on FUN_141717fc0.

The local-player actor is built only inside the block guarded by

    14171800c  lea rax, "interestId"   ; parsed into [rbp+0x268]
    141718247  cmp word ptr [rbp+0x268], 1
    14171824f  jne 0x141718398         ; interestId != 1 -> no actor

Measured live 2026-09-27: that block is never reached (`id_is_1` = 0 hits)
while the record handler runs 283 times, so the actor for the local player is
never constructed and the world renders black with no camera.

This probe reads the parsed values right after each deserialize call:

    141718034  after "interestId"       -> [rbp+0x268]
    141718077  after "clientContextId"  -> [rbp+0x290]

and reports the distribution, so we know whether the capture carries
interestId == 1 anywhere and what the local-player record actually has.
Writes nothing.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const base = Process.findModuleByName('NewWorld.exe').base;
const at = (va) => base.add(va - 0x140000000);

const interest = {};
const ctxid = {};
let n = 0;

function bump(table, key) {
  table[key] = (table[key] || 0) + 1;
}

try {
  Interceptor.attach(at(0x141718034), function () {
    n++;
    try {
      const rbp = this.context.rbp;
      const v = rbp.add(0x268).readU16();
      bump(interest, v);
    } catch (e) { bump(interest, 'err'); }
  });
  send({ ev: 'hooked', at: 'interestId' });
} catch (e) { send({ ev: 'hook-error', at: 'interestId', err: String(e).slice(0, 90) }); }

try {
  Interceptor.attach(at(0x141718077), function () {
    try {
      const rbp = this.context.rbp;
      const v = rbp.add(0x290).readU16();
      bump(ctxid, v);
    } catch (e) { bump(ctxid, 'err'); }
  });
  send({ ev: 'hooked', at: 'clientContextId' });
} catch (e) { send({ ev: 'hook-error', at: 'clientContextId', err: String(e).slice(0, 90) }); }

setInterval(function () {
  send({ ev: 'dist', calls: n, interestId: interest, clientContextId: ctxid });
}, 12000);
send({ ev: 'ready' });
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] interestId observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())