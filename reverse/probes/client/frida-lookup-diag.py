#!/usr/bin/env python3
"""Diagnostic: does the component-lookup hook fire, and what counts does it see?

Read-only, one-shot. Answers whether `FUN_1413fb700(entity, typeId*)` is reached at
all in the current client state and what the largest component count seen is, so a
threshold-based entity tracker can be calibrated instead of guessed.

Usage: python reverse/probes/client/frida-lookup-diag.py --seconds 20
"""

from __future__ import annotations

import argparse
import json
import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let lookups = 0, maxCount = 0, maxEntity = null;
  const histogram = {};

  function compCount(p) {
    try {
      const b = p.add(0x10).readPointer();
      const e = p.add(0x18).readPointer();
      if (b.isNull() || e.isNull()) return -1;
      const n = e.sub(b).toInt32();
      if (n < 0 || n % 8 !== 0 || n > 1 << 20) return -2;
      return n / 8;
    } catch (x) { return -3; }
  }

  Interceptor.attach(rva(0x1413fb700), {
    onEnter(args) {
      lookups++;
      const c = compCount(args[0]);
      const bucket = c < 0 ? ('err' + c) : (c >= 100 ? '>=100' : String(Math.floor(c / 8) * 8));
      histogram[bucket] = (histogram[bucket] || 0) + 1;
      if (c > maxCount) { maxCount = c; maxEntity = args[0].toString(); }
    },
  });

  rpc.exports = {
    stats() {
      return { lookups: lookups, max_count: maxCount, max_entity: maxEntity,
               histogram: histogram };
    },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--process", default="NewWorld.exe")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[diag]", json.dumps(m), flush=True))
    script.load()
    print(f"[diag] attached; sampling for {args.seconds:.0f}s", flush=True)
    end = time.time() + args.seconds
    while time.time() < end:
        try:
            st = script.exports_sync.stats()
            print(f"[diag] {json.dumps(st)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[diag] error: {exc}", flush=True)
        time.sleep(4.0)
    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
