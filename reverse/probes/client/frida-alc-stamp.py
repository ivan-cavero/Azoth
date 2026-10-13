#!/usr/bin/env python3
"""Watch the ALC local client's "last response" stamp and log every time it moves.

WHY THIS IS THE DECISIVE CABLE MEASUREMENT
==========================================
The red HUD cable is a pure client-side age of one 64-bit timestamp, and that timestamp is the
ALC's "last response" time. Two independent functions agree on the formula:

    FUN_14486c740 (icon state):  age = FUN_141413890() - *(self + 0xAA8)
                                 if (age > red) state = 2; else state = (age > amber)
    FUN_14487b300 (debug text):  FUN_141054d80(..., "Time since last response: %s",
                                              format(FUN_141413890() - *(obj + 0xAA8)))

and the second one also prints `Input Latency: %.3f ms  Rollback Count = %u`, so the field is the
ALC's notion of when the server last answered it.

Nothing static found the writer: of the 42 instructions that write `[reg+0xAA8]`, the two that
looked like "store now" are a profiler initialiser and a function-pointer table constructor, and
none of the 42 calls the clock. So this probe measures it instead: hook the per-frame ALC update
to learn the object address, then poll `+0xAA8` and log every change with the clock reading.

WHAT THE RESULT MEANS
=====================
* The stamp is set once and never moves -> nothing we currently send refreshes it, and the icon
  necessarily walks clear -> amber -> red. That is the measured statement of the bug.
* The stamp moves at times T -> correlate T with the server's own event log (`.azoth/logs/world.log`
  has per-second timestamps) and whatever the server sent at T is the refresher. That is how the
  trigger gets identified instead of guessed.

Read-only: it hooks one function, reads two fields, writes nothing.

Usage:
  python az.py probe frida-alc-stamp --timeout 300 --poll 0.1
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

ALC_UPDATE = 0x14486C740  # per-frame ALC local client update; args[0] IS the ALC object
CLOCK = 0x141413890  # the same clock the age is computed against
STAMP_OFFSET = 0xAA8

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const clock = new NativeFunction(rva(0x141413890), 'uint64', []);
  let alc = null;
  let captures = 0;

  // One hook, minimal work: remember the object the client passes to its own ALC update. The
  // hook stays attached but does nothing after the first capture, so it does not distort timing.
  Interceptor.attach(rva(0x14486c740), {
    onEnter(args) {
      if (alc !== null) return;
      try { alc = args[0]; captures++; } catch (e) {}
    },
  });

  rpc.exports = {
    state() {
      if (alc === null) return { ok: false, reason: 'ALC object not seen yet' };
      try {
        const stamp = alc.add(0xaa8).readU64();
        const now = clock();
        return {
          ok: true,
          alc: alc.toString(),
          captures: captures,
          stamp: stamp.toString(),
          now: now.toString(),
          age: (now.sub(stamp)).toString(),
          zero: stamp.equals(0),
        };
      } catch (e) { return { ok: false, reason: String(e) }; }
    },
    teardown() { try { Interceptor.detachAll(); return true; } catch (e) { return String(e); } },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--poll", type=float, default=0.1)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--shutdown", choices=["kill", "detach"], default="kill")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[as]", json.dumps(m), flush=True))
    script.load()
    print(f"[as] attached to {args.process}", flush=True)

    capture = probe_capture(f"alc-stamp-{int(time.time())}.jsonl")
    print(f"[as] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    last_stamp = None
    changes = 0
    first = None
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                st = script.exports_sync.state()
            except Exception as exc:  # noqa: BLE001
                print(f"[as] state error: {exc}", flush=True)
                time.sleep(1.0)
                continue
            if not st.get("ok"):
                time.sleep(0.5)
                continue
            if first is None:
                first = st
                print(f"[as] ALC object {st['alc']}  stamp={st['stamp']} now={st['now']} "
                      f"age={st['age']} zero={st['zero']}", flush=True)
            if st["stamp"] != last_stamp:
                changes += 1
                print(f"[as] STAMP {'initial' if last_stamp is None else 'CHANGED'} -> "
                      f"{st['stamp']}  now={st['now']}  age={st['age']}", flush=True)
                fh.write(json.dumps({"t": time.time(), "event": "stamp", **st}) + "\n")
                fh.flush()
                last_stamp = st["stamp"]
            time.sleep(args.poll)

    print(f"[as] stamp changes observed: {changes}", flush=True)
    if first:
        print(f"[as] first sample: {json.dumps(first)}", flush=True)
        try:
            last = script.exports_sync.state()
            print(f"[as] last sample:  {json.dumps(last)}", flush=True)
        except Exception:  # noqa: BLE001
            pass

    strategy = safe_shutdown(session, script, kill=(args.shutdown == "kill"), device=device,
                             log=lambda m: print(f"[as] {m}", flush=True))
    print(f"[as] shutdown strategy: {strategy}", flush=True)
    print(f"[as] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
