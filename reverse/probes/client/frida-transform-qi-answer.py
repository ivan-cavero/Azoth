#!/usr/bin/env python3
"""Let the client's OWN Transform registration run, by answering the query it asks.

THE IDEA, and why it is different from what failed
=================================================
The Transform gate (`FUN_141763b70`) does, per slice job:

    lVar10 = job->vtable[+0x20](job, {83482F97-84DA-4FD4-BF9E-7FE34C8E091F});
    if (lVar10 != 0) FUN_141582430(lVar10, ...);      // the ONLY GameTransformComponent inserter

Measured 2026-10-19: the gate runs 30 times, `FUN_141582430` runs 0 times, and the QueryInterface
(real, at RVA 0x1445390) accepts `{ED75FE05-…}` and `{B18D903B-…}` (= ReflectContext) but returns
**null** for `{83482F97-…}`.

The earlier attempt bypassed this: it handed a default-constructed transform back from the component
LOOKUP. That removed the 26 warnings and produced 26 `The slice has more than one root` errors plus an
APPCRASH in NewWorld.exe, because it skipped the client's own construction and root bookkeeping.

This probe does the opposite: it makes the QueryInterface ANSWER `{83482F97-…}` with the object
itself, so `FUN_141582430` runs - the client's own registration, on the client's own object, through
the client's own code. Nothing is constructed by us and nothing is written to client memory except
the return value of a query that the client already knows how to handle.

WHAT TO EXPECT, stated before running
=====================================
* If the registration is what the clone path needs, the 26 warnings should drop **and** the slice
  should keep a single root (the failure mode of the previous attempt).
* If the warnings drop but `more than one root` appears again, the registration is not the missing
  piece and this line of attack is finished.
* If the warnings stay at 26, `FUN_141582430` ran but did not seed what the clone reads.

Every outcome is informative, which is why it is worth one run.

Read-only apart from the query's return value. Ends through `device.kill` (hooks hot code).

Usage:
  python az.py probe frida-transform-qi-answer --wait 400 --timeout 240
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

QI = 0x141445390          # job->vtable[+0x20]
REGISTER = 0x141582430    # the only GameTransformComponent inserter
GATE = 0x141763B70
# The type id the gate asks for, little-endian as the 16 bytes it passes.
WANTED = "83482f9784da4fd4bf9e7fe34c8e091f"

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const wanted = %WANTED%;

  let qiCalls = 0, answered = 0, registerCalls = 0, gateCalls = 0;
  const seenGuids = {};

  function hexOf(ptr) {
    try {
      const b = new Uint8Array(ptr.readByteArray(16));
      let h = '';
      for (let i = 0; i < 16; i++) h += ('0' + b[i].toString(16)).slice(-2);
      return h;
    } catch (e) { return null; }
  }

  // THE QUERYINTERFACE. Answer the one GUID it does not know, and pass every other call through
  // untouched so nothing else in the client changes behaviour.
  Interceptor.attach(rva(%QI%), {
    onEnter(args) {
      qiCalls++;
      this.self = args[0];
      this.guid = hexOf(args[1]);
      if (this.guid) seenGuids[this.guid] = (seenGuids[this.guid] || 0) + 1;
      this.want = (this.guid === wanted);
    },
    onLeave(ret) {
      if (!this.want) return;
      if (ret.isNull()) {
        // The client says "I do not implement this". Answer with the object so its own
        // registration path proceeds.
        ret.replace(this.self);
        answered++;
      }
    }
  });

  try {
    Interceptor.attach(rva(%REGISTER%), { onEnter() { registerCalls++; } });
  } catch (e) { send({ev:'attach-error', what:'register', error:String(e)}); }

  try {
    Interceptor.attach(rva(%GATE%), { onEnter() { gateCalls++; } });
  } catch (e) { send({ev:'attach-error', what:'gate', error:String(e)}); }

  send({ ev: 'ready', base: base.toString(16), wanted: wanted });
  setInterval(() => {
    send({ ev: 'stats', qiCalls: qiCalls, answered: answered,
           registerCalls: registerCalls, gateCalls: gateCalls, guids: seenGuids });
  }, 5000);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    source = (JS.replace("%QI%", hex(QI))
                .replace("%REGISTER%", hex(REGISTER))
                .replace("%GATE%", hex(GATE))
                .replace("%WANTED%", json.dumps(WANTED)))
    device = frida.get_local_device()

    def discover():
        return next((p.pid for p in device.enumerate_processes()
                     if p.name.lower() == "newworld.exe"), None)

    pid = discover()
    if pid is None and args.wait:
        deadline = time.time() + args.wait
        while pid is None and time.time() < deadline:
            time.sleep(1)
            pid = discover()
    if pid is None:
        print("[qi] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    out = probe_capture(f"qi-answer-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")
    last: dict = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[qi] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        if fh and not fh.closed:
            fh.write(json.dumps(p) + "\n")
            fh.flush()
        ev = p.get("ev")
        if ev == "ready":
            print(f"[qi] attached base={p['base']} wanted={p['wanted']}", flush=True)
        elif ev == "attach-error":
            print(f"[qi] attach-error {p['what']}: {p['error'][:160]}", flush=True)
        elif ev == "stats":
            last.update(p)
            print(f"[qi] qi={p['qiCalls']} answered={p['answered']} "
                  f"register={p['registerCalls']} gate={p['gateCalls']}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[qi] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    if fh and not fh.closed:
        fh.close()
    print()
    print(f"  FINAL qi={last.get('qiCalls')} answered={last.get('answered')} "
          f"register={last.get('registerCalls')} gate={last.get('gateCalls')}")
    if last.get("registerCalls", 0):
        print("\n  The client's OWN registration ran. Check the warning count and the root errors.")
    else:
        print("\n  Registration still did not run: answering the query is not enough.")
    try:
        script.unload()
    except Exception:
        pass
    try:
        device.kill(pid)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
