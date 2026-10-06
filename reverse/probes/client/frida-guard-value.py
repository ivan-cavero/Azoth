#!/usr/bin/env python3
"""Why does the actor-build guard fail? — read [obj+0x18] at the guard call.

The fourth guard before the local-player actor build is

    1417182ce  call 0x146165ff0(obj, 3)
    1417182d5  je 0x14171836d          ; al == 0 -> skip the actor build

and the callee is a one-liner:

    146165ff0  cmp dword ptr [rcx + 0x18], edx
    146165ff3  setae al                ; al = ([obj+0x18] >= id)
    146165ff6  ret

Measured 2026-09-27: the call site is reached 25 times (interestId == 1 passed
25 times) and the actor build is entered 0 times, so [obj+0x18] is below 3 for
the local-player record.

This probe reads the exact pair ([obj+0x18], id) at every call and reports the
distribution, so we know what the record is missing. Writes nothing.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const base = Process.findModuleByName('NewWorld.exe').base;
const at = (va) => base.add(va - 0x140000000);

const pairs = {};
let n = 0;

// The guard call site, so we only see the actor-build decision.
try {
  Interceptor.attach(at(0x1417182CE), function () {
    n++;
    try {
      const obj = this.context.rcx;
      const field = obj.add(0x18).readU32();
      const id = this.context.rdx.toInt32();
      const key = 'field18=' + field + ' id=' + id;
      pairs[key] = (pairs[key] || 0) + 1;
      if (n <= 6) {
        send({ ev: 'GUARD', n: n, obj: obj.toString(), field18: field, id: id });
      }
    } catch (e) { pairs['err'] = (pairs['err'] || 0) + 1; }
  });
  send({ ev: 'hooked', at: 'guard-call-site' });
} catch (e) {
  send({ ev: 'hook-error', err: String(e).slice(0, 90) });
}

setInterval(function () { send({ ev: 'dist', calls: n, pairs: pairs }); }, 10000);
send({ ev: 'ready' });
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] guard-value observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())