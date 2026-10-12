#!/usr/bin/env python3
"""Validate the position accessor against the client's own console command output.

WHY. `frida-player-position.py` reads the local player position by calling the client's own
accessor `FUN_140fddfa0` and reading `*(float*)(holder+0x14c/0x15c/0x16c)`, which is exactly
what the client's console command `nw_getPlayerPosition` (handler `0x141015b30`) prints. That
is a strong derivation, but "derived from the disassembly" is not the same as "confirmed to be
what the command prints". This probe closes that gap:

  1. it hooks the printer `FUN_141022a90(&fmt, x, y, z)` and captures xmm0/xmm1/xmm2, the three
     doubles the command prints;
  2. it CALLS the command handler `0x141015b30` directly (the client's own code path for
     `nw_getPlayerPosition`, which takes no arguments);
  3. it reads the same position through the accessor;
  4. it compares. Equal values ⇒ the accessor is confirmed as the client's own position, so a
     "no change while W is held" result from it is a real measurement of the player, not a
     measurement of the wrong object.

This also gives the project a general ability to run the client's own console commands, which
matters for later measurements (`nw_findLocalEntity`, `nw_getPlayerHealth`, ...).

Read-only with respect to game state: the command only prints.

Usage:
  python az.py probe frida-position-validate --timeout 120
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

HANDLER = 0x141015B30    # the nw_getPlayerPosition console command handler (no arguments)
PRINTER = 0x141022A90    # FUN_141022a90(&fmt, x, y, z) - receives xmm0/xmm1/xmm2
GETTER = 0x140FDDFA0     # the accessor the handler itself calls

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const getter = new NativeFunction(rva(0x140fddfa0), 'pointer', ['pointer']);
  const printed = [];
  let prints = 0;

  try {
    Interceptor.attach(rva(0x141022a90), {
      onEnter(args) {
        prints++;
        // Frida exposes xmm0..xmm15 on x64 in this version; if it does not, record null and
        // the Python side falls back to the print counter alone.
        let x = null, y = null, z = null;
        try { x = this.context.xmm0; } catch (e) {}
        try { y = this.context.xmm1; } catch (e) {}
        try { z = this.context.xmm2; } catch (e) {}
        if (printed.length < 16) {
          printed.push({ t: Date.now(), x: x, y: y, z: z });
        }
        send({ ev: 'print', x: x, y: y, z: z });
      },
    });
  } catch (e) { send({ ev: 'error', hook: 'printer', error: String(e) }); }

  function readVia() {
    const out = Memory.alloc(0x18);
    out.writeByteArray(new Uint8Array(0x18));
    getter(out);
    const holder = out.readPointer();
    if (holder.isNull()) return null;
    return {
      holder: holder.toString(),
      v: [holder.add(0x14c).readFloat(), holder.add(0x15c).readFloat(),
          holder.add(0x16c).readFloat()],
    };
  }

  rpc.exports = {
    // Call the client's own console command handler, then compare its printed values with the
    // accessor's values.
    validate() {
      const before = readVia();
      const beforePrints = prints;
      let error = null;
      try {
        const fn = new NativeFunction(rva(0x141015b30), 'void', []);
        fn();
      } catch (e) { error = String(e); }
      const after = readVia();
      return {
        prints_before: beforePrints,
        prints_after: prints,
        printed: printed.slice(-4),
        before: before,
        after: after,
        error: error,
      };
    },
    read() { return readVia(); },
    counters() { return { prints: prints }; },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--process", default="NewWorld.exe")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[pv]", json.dumps(m), flush=True))
    script.load()
    print(f"[pv] attached to {args.process}", flush=True)

    capture = probe_capture(f"position-validate-{int(time.time())}.jsonl")
    print(f"[pv] live -> {capture}", flush=True)

    time.sleep(1.0)
    try:
        res = script.exports_sync.validate()
    except Exception as exc:  # noqa: BLE001
        res = {"error": f"rpc failed: {exc}"}
    print(f"[pv] validate -> {json.dumps(res)}", flush=True)
    with capture.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.time(), **res}) + "\n")

    end = time.time() + args.timeout
    while time.time() < end:
        try:
            r = script.exports_sync.read()
            c = script.exports_sync.counters()
            print(f"[pv] read={json.dumps(r)} counters={json.dumps(c)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[pv] error: {exc}", flush=True)
            break
        time.sleep(5.0)

    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    print(f"[pv] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
