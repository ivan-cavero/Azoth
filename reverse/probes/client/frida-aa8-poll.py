#!/usr/bin/env python3
"""Poll the connection object's +0xAA8 (the 'last response' stamp) and log changes.

The HUD 'Time since last response' prints `now - *(obj+0xAA8)`. In a working
session that stamp must be refreshed whenever the server answers; the user sees
the gauge only climb. The previous probe used MemoryAccessMonitor, which
DISARMS after its first hit (so 'one access' proved nothing). This probe takes
the object from FUN_14486c740 (rcx) and then samples *(obj+0xAA8) every 250 ms,
logging every change, every 5 s for a heartbeat, and the exact wall-clock delta.

Private runtime only (no EAC). Read-only.

Usage: python scripts/frida-aa8-poll.py [--timeout 300]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  let aa8 = null, obj = null;
  Interceptor.attach(off(0x14486c740), {
    onEnter(args) {
      if (aa8) return;
      obj = args[0];
      if (obj.isNull()) return;
      aa8 = obj.add(0xaa8);
      send({ev:'object', obj: obj.toString(), aa8: aa8.toString(), first: aa8.readU64().toString()});
    }
  });
  let last = null, ticks = 0;
  setInterval(function () {
    if (!aa8) return;
    ticks++;
    let v = aa8.readU64();
    if (last === null) { last = v; return; }
    if (!v.equals(last)) {
      send({ev:'CHANGE', from: last.toString(), to: v.toString(), delta: v.sub(last).toString()});
      last = v;
    } else if (ticks % 20 === 0) {
      send({ev:'steady', value: v.toString(), ticks: ticks});
    }
  }, 250);
  send({ev:'ready', base: base.toString(16)});
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    out = Path(__file__).resolve().parent.parent / "sessions" / f"aa8-poll-{int(time.time())}.jsonl"
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
    print(f"[aa8-poll] live -> {out}", flush=True)
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
