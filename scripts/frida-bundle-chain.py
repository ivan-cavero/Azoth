#!/usr/bin/env python3
"""Where does the local-player record die? — Frida chain probe.

The client never logs `Received new local player metadata` (the record-id-1
path in FUN_141717fc0), so the local player actor is never created and the
world renders black with no camera. This probe hooks every link of the
StateBundle chain and reports which ones actually run during a world attempt:

    0x14643e7b0  HandleUnexpectedMessage / bundle dispatcher
    0x146448cd0  LoadContextAndLevel
    0x14175ccc0  StateBundle handler (loops the records)
    0x146af20d0  record parser ([record_id][fragment_count] + fragments)
    0x146af2340  fragment processor
    0x141717fc0  local-player record handler (logs "Received new local player
                 metadata" for record id 1)

Writes nothing. Private runtime only (no EAC in-process; the kernel hook on
LoadContextAndLevel/the reader does not cover these entries).
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

const TARGETS = [
  ['dispatcher', 0x14643E7B0],
  ['loadctx',    0x146448CD0],
  ['bundle',     0x14175CCC0],
  ['recparse',   0x146AF20D0],
  ['fragproc',   0x146AF2340],
  ['localplayer',0x141717FC0],
];

const counts = {};
for (const [name, va] of TARGETS) {
  counts[name] = 0;
  try {
    const b = Array.from(new Uint8Array(at(va).readByteArray(4)))
      .map((x) => x.toString(16).padStart(2, '0')).join(' ');
    send({ ev: 'entry-bytes', fn: name, bytes: b });
  } catch (e) {
    send({ ev: 'entry-bytes', fn: name, err: String(e).slice(0, 60) });
  }
  try {
    Interceptor.attach(at(va), (function (n) {
      return function (args) {
        counts[n]++;
        if (counts[n] <= 4) {
          send({ ev: 'HIT', fn: n, n: counts[n], arg0: args[0].toString() });
        }
      };
    })(name));
    send({ ev: 'hooked', fn: name });
  } catch (e) {
    send({ ev: 'hook-error', fn: name, err: String(e).slice(0, 90) });
  }
}

setInterval(function () {
  send({ ev: 'counts', counts: counts });
}, 15000);
send({ ev: 'ready' });
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] bundle-chain observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())