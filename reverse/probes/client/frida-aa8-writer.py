#!/usr/bin/env python3
"""Find what writes the connection object's +0xAA8 (the 'last response' stamp).

FUN_14487b300 (the debug HUD) prints "Time since last response" as
`now - *(obj+0xAA8)`; FUN_14486c740 reads the same field. The client shows that
gauge climbing and never resetting, i.e. whatever is supposed to stamp +0xAA8
never runs. This probe:

  1. hooks FUN_14486c740 (runs per-frame) to grab the object pointer (rcx);
  2. arms MemoryAccessMonitor on [obj+0xAA8, 8] and logs every access with the
     faulting instruction address, so the writer becomes visible.

Private runtime only (no EAC). Read-only.

Usage: python scripts/frida-aa8-writer.py [--timeout 300]
"""

from __future__ import annotations

import argparse
import ctypes
import time
from pathlib import Path

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  let armed = false;
  const seen = {};
  Interceptor.attach(off(0x14486c740), {
    onEnter(args) {
      if (armed) return;
      const obj = args[0];
      if (obj.isNull()) return;
      armed = true;
      send({ev:'object', obj: obj.toString(), aa8: obj.add(0xaa8).toString()});
      try {
        MemoryAccessMonitor.enable(
          [{base: obj.add(0xaa8), size: 8}],
          {
            onAccess(details) {
              const key = details.from.toString(16);
              seen[key] = (seen[key] || 0) + 1;
              send({ev:'access', op: details.operation, from: details.from.sub(base).toString(16),
                    pc: details.address.toString(), count: seen[key]});
            }
          }
        );
      } catch (e) { send({ev:'arm-error', msg: String(e)}); }
    }
  });
  send({ev:'ready', base: base.toString(16)});
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    out = Path(__file__).resolve().parent.parent / "sessions" / f"aa8-writer-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            print(m["payload"], flush=True)
            fh.write(str(m["payload"]) + "\n")
            fh.flush()
        else:
            print("err:", str(m.get("description"))[:200], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[aa8] probe live -> {out}", flush=True)
    try:
        end = time.time() + args.timeout
        while time.time() < end:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
