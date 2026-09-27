#!/usr/bin/env python3
"""Resolve the LoadContextAndLevel predicate: [pGame+0x28]->vtable[0x88].

`LoadContextAndLevel` (0x146448CD0) decides between "load the level" and
"mark failed + Cleanup" with one virtual call, made twice:

    146448e8c  call qword ptr [rdx+0x88]   ; 1st — result is passed to Initialize
    146448f67  call qword ptr [rax+0x88]   ; 2nd — result decides the branch
    146448f72  jne  0x1464490e1            ; non-zero -> failure -> Cleanup

Receiver: `local_res18 = *(pGame + 0x60) + 0x28`, i.e. the level streaming
manager. Its vtable only exists at runtime, so the slot cannot be resolved
statically — but it CAN be read from the live process, and then the exact
target address is converted to an RVA so the function can be disassembled
offline.

Implementation note: hook FUNCTION ENTRIES only. An earlier version hooked
the `call` instruction at 0x146448E8C directly and never fired; hooking the
function that contains those calls is reliable (the same technique the
Cleanup probe used successfully).

Build 1.400.6031.6004151. Private runtime only (no EAC).
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
  const rva = (p) => '0x' + p.sub(base).toString(16);

  const LOAD = at(0x146448CD0);   // LoadContextAndLevel(param_1 = ctx)
  const INIT = at(0x14171B850);   // clientContext->Initialize
  const CLEAN = at(0x146455E90);  // Cleanup

  const PTR_GAME = at(0x14A7BA0E0);   // global holding pGame
  const OFF_GAME = 0x60;
  const PRED_SLOT = 0x88;

  let seen = 0;
  let cleanupN = 0;

  function resolvePredicate() {
    try {
      const holder = PTR_GAME.readPointer();
      const pGame = holder.add(OFF_GAME).readPointer();
      if (pGame.isNull()) return {err: 'pGame null'};
      const mgr = pGame.add(0x28);
      const vt = mgr.readPointer();
      if (vt.isNull()) return {err: 'vtable null', pGame: pGame.toString()};
      const fn = vt.add(PRED_SLOT).readPointer();
      return {
        pGame: pGame.toString(),
        mgr: mgr.toString(),
        vtable: vt.toString(), vtable_rva: rva(vt),
        predicate: fn.toString(), predicate_rva: rva(fn),
      };
    } catch (e) {
      return {err: String(e)};
    }
  }

  function stateOf(ctx) {
    const out = {ctx: ctx.toString()};
    for (const [name, off] of [['selfIdent', 0x1A0], ['haveLevelInfo', 0x1A1],
                               ['failed', 0x1A2]]) {
      try { out[name] = ctx.add(off).readU8(); } catch (e) { out[name] = 'err'; }
    }
    return out;
  }

  Interceptor.attach(LOAD, {
    onEnter(args) {
      seen++;
      send({ev: 'load-enter', n: seen, state: stateOf(args[0]),
            predicate: resolvePredicate()});
    },
    onLeave(ret) {
      send({ev: 'load-leave', n: seen});
    }
  });

  Interceptor.attach(INIT, {
    onEnter(args) {
      // args[0..5]: sdk, name, world, ?, ctx+0x148, flag, predicateResult
      let pr = null;
      try { pr = args[6].toInt32(); } catch (e) { pr = 'err:' + e; }
      send({ev: 'init-enter', predicateArg: pr, obj: args[0].toString()});
    },
    onLeave() { send({ev: 'init-leave'}); }
  });

  Interceptor.attach(CLEAN, {
    onEnter(args) {
      cleanupN++;
      let frames = [];
      try {
        frames = Thread.backtrace(this.context, Backtracer.ACCURATE)
          .slice(0, 4).map((a) => rva(a));
      } catch (e) { frames = ['err']; }
      send({ev: 'cleanup-enter', n: cleanupN, obj: args[0].toString(),
            frames: frames});
    }
  });

  send({ev: 'ready'});
  // Resolve immediately at attach time: the globals are already populated,
  // so the predicate identity does not require a world attempt.
  send({ev: 'resolve-now', predicate: resolvePredicate()});
}
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] predicate observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
