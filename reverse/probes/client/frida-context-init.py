#!/usr/bin/env python3
"""Observe ClientContext lazy-init on the private (no-EAC) runtime.

The 1.400 dispatcher calls FUN_146448cd0 before logging
`ReceiveStateBundle ... clientContext == nullptr`. This probe logs only
entry/return state and the lazy-init flush; it never writes process memory.
"""
from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({error:'no-module'}); }
else {
  const base = mod.base;
  const at = (va) => base.add(va - 0x140000000);
  const init = at(0x146448CD0);
  const flush = at(0x146455E90);
  const msg = at(0x14643E7B0);
  let n = 0;
  let watchedTarget = null;
  let watchAttempted = false;
  function watchField(p) {
    const target = p.add(0x190);
    if (watchedTarget && watchedTarget.equals(target)) return;
    if (watchAttempted) return;
    watchAttempted = true;
    try {
      watchedTarget = target;
      MemoryAccessMonitor.enable({base: target, size: 1}, {
        onAccess(details) {
          if (!details.address.equals(target) || details.operation !== 'write') return;
          let frames = [];
          try {
            frames = Thread.backtrace(this.context, Backtracer.ACCURATE)
              .map(DebugSymbol.fromAddress).map(String);
          } catch (e) {
            frames = ['backtrace-error: ' + e];
          }
          send({ev:'field190-write', target:target.toString(),
                from:details.from.toString(), frames:frames});
          try { MemoryAccessMonitor.disable(); } catch (_) {}
        }
      });
      send({ev:'field190-watch', target:target.toString()});
    } catch (e) {
      send({ev:'field190-watch-error', error:String(e)});
    }
  }
  function u8(p) { try { return p.readU8(); } catch (_) { return -1; } }
  function u32(p) { try { return p.readU32(); } catch (_) { return -1; } }
  function u64(p) { try { return p.readU64().toString(); } catch (_) { return '?'; } }
  function ptr(p) { try { return p.readPointer().toString(); } catch (_) { return '?'; } }
  function snap(p) {
    return {
      p: p.toString(),
      currentCtx: u8(p.add(0x80)),
      expected: u64(p.add(0x70)),
      f1a0: u8(p.add(0x1a0)),
      f1a1: u8(p.add(0x1a1)),
      f1a2: u8(p.add(0x1a2)),
      ptr190: ptr(p.add(0x190)),
      ptr198: ptr(p.add(0x198)),
      ptr1a8: ptr(p.add(0x1a8)),
    };
  }
  Interceptor.attach(init, {
    onEnter(args) {
      n++;
      watchField(args[0]);
      if (n <= 3) send({ev:'ctx-init-enter', n, state:snap(args[0])});
    },
    onLeave(retval) {
      send({ev:'ctx-init-leave', n, ret:retval.toString()});
    }
  });
  Interceptor.attach(flush, {
    onEnter(args) {
      if (n <= 3) send({ev:'ctx-flush-enter', state:snap(args[0])});
    },
    onLeave(retval) {
      if (n <= 3) send({ev:'ctx-flush-leave', ret:retval.toString()});
    }
  });
  send({ev:'ready', init:init.toString(), flush:flush.toString()});
}
"""

def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] context-init observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
