#!/usr/bin/env python3
"""Hook all 61 code sites that reference the manager singleton storage.

The storage lives at 0x14a2fb9f0 (TLS slot 0x3684); the lazy getter is
FUN_141026080. The spawn gate reads the manager's +8 (the local player's
entity id) and it never gets written, so the writer must be one of the
sites that reach this storage. Hooking every reference and counting which
ones fire during the world load isolates the binder without guessing
displacement patterns.

Expect the hot sites to be the getter plus the per-frame gate callers; the
site that fires once, right as the type 0x8 bundles land, is the one that
populates +8.
"""

from __future__ import annotations

import time

import frida

# Reproduce the reference list with the exact scan that works
# (48/4c 8b/89/8d/3b [rip+disp32] == storage).
REFS = [
    0x14100A7C7, 0x14100A803, 0x14100A816, 0x1410260A9, 0x14102610C,
    0x14257B686, 0x14257B8D7, 0x1427DAF89, 0x1427DB0DC, 0x14288E8B9,
    0x14288EB24, 0x1428B56E0, 0x1428B5764, 0x142904F9D, 0x142905370,
    0x142C17389, 0x142C174B8, 0x1430F1535, 0x1430F231C, 0x1431192EC,
    0x1431193E9, 0x143143730, 0x1431437C5, 0x143162380, 0x1431623F8,
    0x1432F0855, 0x1432F0976, 0x143482CB9, 0x143482E0C, 0x143638CB8,
    0x14363904C, 0x14387590C, 0x143875B36, 0x1438ABE84, 0x1438ABF62,
    0x14391F576, 0x14391F67F, 0x1439D53A3, 0x1439D54A3, 0x143BB8E6E,
    0x143BB8FB3, 0x143D87AFC, 0x143D87C4A, 0x143DDB1B8, 0x143DDB2EE,
    0x143FED295, 0x143FED31B, 0x14419B039, 0x14419B183, 0x1443109FC,
    0x144310B31, 0x14436A2C5, 0x14436A4C7, 0x144489817, 0x1444899EB,
    0x1448AA11F, 0x1448AA34E, 0x144958F71, 0x144959006, 0x145D75B66,
    0x145D75F15,
]

JS_HEAD = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const counts = {};
const REFS = __REFS__;
let firstSeen = {};

for (const va of REFS) {
  const addr = base.add(va - 0x140000000);
  // Attach at the containing instruction's start. Frida wants a function
  // entry for Interceptor; use a one-shot Stalker-free trampoline by
  // attaching the nearest preceding function entry instead is fragile, so
  // count via a cheap inline read of the instruction pointer using
  // Interceptor at the exact address (works for most non-prelude sites).
  try {
    Interceptor.attach(addr, {
      onEnter() {
        const k = va.toString(16);
        counts[k] = (counts[k] || 0) + 1;
        if (firstSeen[k] === undefined) firstSeen[k] = Date.now();
      }
    });
  } catch (e) {
    counts['ERR:' + va.toString(16)] = 1;
  }
}

setInterval(function () {
  send({ev: 'counts', counts: counts, t: Date.now()});
}, 2000);
send({ev: 'probe-ready', sites: REFS.length});
"""


def main() -> int:
    js = JS_HEAD.replace("__REFS__", "[" + ",".join(str(v) for v in REFS) + "]")
    session = frida.attach("NewWorld.exe")
    script = session.create_script(js)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] manager storage refs armed (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
