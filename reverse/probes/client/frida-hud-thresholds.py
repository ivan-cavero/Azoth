#!/usr/bin/env python3
"""Read the client's HUD connection thresholds and the ALC stamp, live.

WHY. The red cable icon is a pure function of `now - *(conn+0xAA8)` compared against
two globals (`FUN_14486c740`):

    uVar25 = FUN_141413890() - *(longlong *)(param_1 + 0xaa8);
    if (_DAT_149f21054 < uVar25) state = 2;            // RED
    else state = (_DAT_149f20f9c < uVar25);            // 1 = amber, 0 = ok

Both globals are **zero in the file** — they are lazily filled from cvars on first
read, so only a live process shows the real numbers. The candidate cvars are
`javelin.alc-server-timeout-for-input` (2000), `-for-ui` (2000) and `-for-ui-high`
(15000), registered by `FUN_1410825e0`. Reading the two globals after the HUD has run identifies the measured amber and red
color thresholds. It does not diagnose the separate 20-minute return-to-menu timer.

It also reads `conn+0xAA8` and `conn+0xAA0` together with `FUN_141413890()`, so the
age of the stamp and the state of the ALC pointer can be seen in one sample.

Read-only. Private no-EAC client.

Usage:
  python az.py probe frida-hud-thresholds --timeout 120
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

RED = 0x149F21054
AMBER = 0x149F20F9C
PERFRAME = 0x14486C740
NOW = 0x141413890

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const nowFn = new NativeFunction(rva(0x141413890), 'uint64', []);
  const red = rva(0x149f21054);
  const amber = rva(0x149f20f9c);
  let obj = null;

  Interceptor.attach(rva(0x14486c740), {
    onEnter(args) { if (obj === null && !args[0].isNull()) obj = args[0]; }
  });

  rpc.exports = {
    read() {
      let out = { now: nowFn().toString() };
      try { out.red_threshold = red.readU64().toString(); } catch (e) { out.red_err = String(e); }
      try { out.amber_threshold = amber.readU64().toString(); } catch (e) { out.amber_err = String(e); }
      if (obj !== null) {
        out.conn = obj.toString();
        try {
          const stamp = obj.add(0xaa8).readU64();
          out.stamp = stamp.toString();
          out.age_ms = nowFn().sub(stamp).toNumber();
        } catch (e) { out.stamp_err = String(e); }
        try { out.alc_ptr_aa0 = obj.add(0xaa0).readPointer().toString(); } catch (e) {}
      }
      return out;
    }
  };

  send({ ev: 'ready', base: base.toString(16) });
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--poll", type=float, default=10.0)
    args = ap.parse_args()

    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[2] / "sessions" / f"hud-thresholds-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")
    script.on("message", lambda m, d: print("[thr]", m.get("payload", m), flush=True))
    script.load()

    end = time.time() + args.timeout
    while time.time() < end:
        try:
            st = script.exports_sync.read()
        except Exception as exc:  # noqa: BLE001
            print("[thr] read error:", exc, flush=True)
            time.sleep(args.poll)
            continue
        fh.write(json.dumps(st) + "\n")
        fh.flush()
        print(f"[thr] {json.dumps(st)}", flush=True)
        time.sleep(args.poll)
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
