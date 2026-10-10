#!/usr/bin/env python3
"""Measure how many bytes the client consumes per state-bundle fragment.

WHY. `FUN_146af2340` is the per-fragment reader in the VERIFIED bundle path
(FUN_14643e7b0 -> FUN_146455e90 -> FUN_14175ccc0 -> FUN_146af20d0 ->
FUN_146af2340, every edge a real call). Our parse says a fragment is
`[varint key][varint type][3 bytes][varint length][payload]`, derived from the
capture consuming its body exactly. That is self-consistent but it is not proof
the client reads the same fields. This probe settles it: the decode context
carries a cursor at [ctx + 0x10] (the field FUN_14087b5c0 advances), so the
cursor delta across one FUN_146af2340 call IS the number of bytes the client
actually consumed for that fragment. If the client's total per bundle equals
ours, the layout is right; if not, the length field or the header is wrong.

Read-only.

Usage: python az.py probe frida-fragment-bytes [--timeout 180]
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  let n = 0;
  Interceptor.attach(off(0x146af2340), {
    onEnter(args) {
      this.ctx = null;
      this.before = null;
      try {
        this.ctx = args[0].readPointer();
        this.before = this.ctx.add(0x10).readPointer();
      } catch (e) { this.err = String(e); }
    },
    onLeave(ret) {
      n++;
      if (n > 40) return;
      let delta = null, accepted = null;
      try {
        const after = this.ctx.add(0x10).readPointer();
        delta = after.sub(this.before).toInt32();
        accepted = (ret.toInt32() !== 0);
      } catch (e) { delta = 'err:' + e; }
      send({ev:'fragment', n: n, consumed: delta, accepted: accepted});
    }
  });
  setInterval(function(){ send({ev:'alive', n: n}); }, 5000);
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", default="fragment-bytes.jsonl")
    args = parser.parse_args()
    out_path = probe_capture(args.out)
    device = frida.get_local_device()
    session = None
    for _ in range(90):
        try:
            session = device.attach("NewWorld.exe")
            break
        except Exception:
            time.sleep(2)
    if session is None:
        raise SystemExit("could not attach to NewWorld.exe")
    script = session.create_script(JS)
    handle = out_path.open("w", encoding="utf-8")

    def on_message(message, _data):
        payload = message.get("payload") if message.get("type") == "send" else message
        handle.write(json.dumps(payload) + "\n")
        handle.flush()

    script.on("message", on_message)
    script.load()
    print(f"attached; logging to {out_path}")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(5)
    try:
        session.detach()
    except Exception:
        pass
    handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
