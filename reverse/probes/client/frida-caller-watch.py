#!/usr/bin/env python3
"""Which Cleanup caller fires? — hook all four call sites.

There are exactly 4 `call 0x146455E90` in .text:

    0x145A951BC  teardown helper (called from the two guards)
    0x14643EB8B  inside FUN_14643E980 (after FUN_14644B280 != 0)
    0x14643EC98  inside FUN_14643E980 (after FUN_141717A20)
    0x1464490F3  LoadContextAndLevel failure branch (jne at 0x146448F72)

Hooking the `call` instruction cannot work reliably, so instead hook the
FUNCTIONS that contain them and the teardown helper:

    0x145A95160  teardown helper
    0x14643E980  the unknown function (resolve its start; 0x14643E980 is the
                 nearest int3 boundary — verify with the probe)
    0x146448CD0  LoadContextAndLevel
    0x141717A20  the call right before the 0x14643EC98 cleanup

Each hit logs a timestamped event. The one that fires right before the
`Initialize -> Cleanup` pair in Game.log is the real path.

Nothing is written to the process. Private runtime only (no EAC).
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

const TARGETS = [
  ['teardown', 0x145A95160],
  ['fn_43e9', 0x14643E980],
  ['loadctx', 0x146448CD0],
  ['fn_1717a20', 0x141717A20],
  ['cleanup', 0x146455E90],
];

for (const [name, va] of TARGETS) {
  try {
    Interceptor.attach(at(va), {
      onEnter(args) {
        send({ev: 'enter', fn: name, rc: args[0].toString()});
      }
    });
    send({ev: 'hooked', fn: name});
  } catch (e) {
    send({ev: 'hook-error', fn: name, error: String(e)});
  }
}
send({ev: 'ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] caller watcher active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
