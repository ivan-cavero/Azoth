#!/usr/bin/env python3
"""Who calls ClientContext::Cleanup? — Frida backtrace probe.

`LoadContextAndLevel` calls `clientContext->Initialize()`
(0x14171B850) and, in the SAME millisecond, `Cleanup()`, so every later
state bundle is dropped with `clientContext == nullptr`. Patching the
`[obj+0x88]` predicate flag AND its failure branch did NOT stop the
cleanup, which means the trigger is somewhere else.

This probe writes nothing: it hooks the two functions that bracket the
logged pair and prints an accurate backtrace plus the receiver's field
state, so the caller is identified instead of guessed.

Targets:
  0x14171B850  clientContext->Initialize()   (logs "[ClientContext] Initialize()")
  0x146455E90  the Cleanup/flush pair         (logs "[ClientContext] Cleanup()")
  0x146448CD0  LoadContextAndLevel            (the dispatcher)

Build 1.400.6031.6004151. Private runtime only (no EAC) — see
research/docs/EAC.md for the scoped ban.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({error: 'no-module'}); }
else {
  const base = mod.base;
  const at = (va) => base.add(va - 0x140000000);

  const INIT = at(0x14171B850);
  const CLEAN = at(0x146455E90);
  const LOAD = at(0x146448CD0);

  let initN = 0;
  let cleanN = 0;

  function frames(ctx) {
    try {
      return Thread.backtrace(ctx, Backtracer.ACCURATE)
        .map((a) => {
          const s = DebugSymbol.fromAddress(a);
          const off = a.sub(base);
          return (s.name ? s.name + ' ' : '') + a.toString() +
                 ' (NewWorld+' + off.toString() + ')';
        });
    } catch (e) {
      return ['backtrace-error: ' + e];
    }
  }

  function snapshot(p) {
    const out = {p: p ? p.toString() : null};
    if (!p) return out;
    const fields = {0x80: 'u8', 0x180: 'u8', 0x190: 'ptr', 0x198: 'ptr',
                    0x1a0: 'u8', 0x1a1: 'u8', 0x1a2: 'u8'};
    for (const k in fields) {
      const a = p.add(parseInt(k));
      try {
        out['f' + k] = fields[k] === 'ptr'
          ? a.readPointer().toString()
          : a.readU8();
      } catch (e) { out['f' + k] = 'err'; }
    }
    return out;
  }

  Interceptor.attach(INIT, {
    onEnter(args) {
      initN++;
      send({ev: 'init-enter', n: initN, rc: args[0].toString(), state: snapshot(args[0]),
            frames: frames(this.context)});
    },
    onLeave(ret) {
      send({ev: 'init-leave', n: initN, ret: ret.toString(), state: snapshot(null)});
    }
  });

  Interceptor.attach(CLEAN, {
    onEnter(args) {
      cleanN++;
      send({ev: 'cleanup-enter', n: cleanN, rc: args[0].toString(),
            state: snapshot(args[0]), frames: frames(this.context)});
    },
    onLeave(ret) {
      send({ev: 'cleanup-leave', n: cleanN, ret: ret.toString()});
    }
  });

  Interceptor.attach(LOAD, {
    onEnter(args) {
      send({ev: 'load-enter', rc: args[0].toString(), frames: frames(this.context)});
    },
    onLeave(ret) {
      send({ev: 'load-leave', ret: ret.toString()});
    }
  });

  send({ev: 'ready', init: INIT.toString(), cleanup: CLEAN.toString(), load: LOAD.toString()});
}
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] cleanup backtrace observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
