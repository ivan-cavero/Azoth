#!/usr/bin/env python3
"""Does the GameTransformComponent REGISTRATION path ever run, and if not, where does it stop?

WHY. The `Couldn't get Transform component` gap has been narrowed to one function. `FUN_141763b70`
(decompiled 2026-10-19) is:

    if (param_1 != 0) {
        lVar10 = param_1->vtable[+0x20](param_1, FUN_1407fbe80());   // the gate
    }
    if (lVar10 != 0) {
        FUN_141582430(lVar10, ...);      // <-- the ONLY function that registers
                                         //     {484AE67D-...} GameTransformComponent
    }

So the registration happens exactly when that virtual call returns non-null. Repairing the LOOKUP's
answer (2026-10-19) was tried and rejected: it removed the 26 warnings and produced 26
`The slice has more than one root` errors plus an APPCRASH. The question this probe answers is the one
BEFORE that: **is `FUN_141763b70` even reached at runtime, and does its gate return null?**

That distinction decides everything downstream:
  * gate never reached  -> the class map is never seeded, and the fix is to reach the gate;
  * gate reached, null  -> the interface lookup fails, and the fix is at the interface;
  * gate reached, non-null -> registration DOES happen, and the gap is later than believed.

Read-only: it hooks three entry points and counts. Ends through `device.kill` because it hooks code
the client calls continuously (a bare detach is the measured execute-after-unload crash).

Usage:
  python az.py probe frida-transform-gate --wait 400 --timeout 240
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

GATE = 0x141763B70          # the function above
REGISTER = 0x141582430      # the only inserter of GameTransformComponent
LOOKUP_VT = 0x1413FB700     # the component lookup, as a control that the session is live

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);

  let gateCalls = 0, gateNonNull = 0, gateNull = 0, registerCalls = 0, lookupCalls = 0;

  // THE GATE. Its return value is what decides whether registration runs, so onLeave is correct
  // here: FUN_141763b70 is a whole function, so Frida's leave fires when it returns.
  try {
    Interceptor.attach(rva(%GATE%), {
      onEnter(args) { this.p = args[0]; },
      onLeave(ret) {
        gateCalls++;
        let nonNull = false;
        try { nonNull = !ret.isNull(); } catch (e) {}
        // The gate function itself returns void, so the interesting value is not its return but
        // whether the REGISTER call happened - which is counted separately. What is recorded here
        // is simply that the function ran, and with which argument.
        send({ ev: 'gate', arg: this.p ? this.p.toString() : null, n: gateCalls });
      }
    });
  } catch (e) { send({ev:'attach-error', what:'gate', error:String(e)}); }

  // THE REGISTER. If this ever fires, the class map WAS seeded.
  try {
    Interceptor.attach(rva(%REGISTER%), {
      onEnter(args) {
        registerCalls++;
        send({ ev: 'register', a0: args[0].toString(), a1: args[1].toString(), n: registerCalls });
      }
    });
  } catch (e) { send({ev:'attach-error', what:'register', error:String(e)}); }

  // Control: the lookup runs thousands of times per second in a live session, so it proves the
  // probe is attached to the right process.
  try {
    Interceptor.attach(rva(%LOOKUP%), { onEnter() { lookupCalls++; } });
  } catch (e) { send({ev:'attach-error', what:'lookup', error:String(e)}); }

  send({ ev: 'ready', base: base.toString(16) });
  setInterval(() => {
    send({ ev: 'stats', gateCalls: gateCalls, registerCalls: registerCalls,
           lookupCalls: lookupCalls });
  }, 5000);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    source = (JS.replace("%GATE%", hex(GATE))
                .replace("%REGISTER%", hex(REGISTER))
                .replace("%LOOKUP%", hex(LOOKUP_VT)))

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
        print("[gate] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    out = probe_capture(f"transform-gate-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")
    last: dict = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[gate] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        if fh and not fh.closed:
            fh.write(json.dumps(p) + "\n")
            fh.flush()
        ev = p.get("ev")
        if ev == "ready":
            print(f"[gate] attached base={p['base']}", flush=True)
        elif ev == "gate":
            print(f"[gate] GATE RAN n={p['n']} arg={p['arg']}", flush=True)
        elif ev == "register":
            print(f"[gate] *** REGISTER CALLED n={p['n']} a0={p['a0']} a1={p['a1']}", flush=True)
        elif ev == "attach-error":
            print(f"[gate] attach-error {p['what']}: {p['error'][:160]}", flush=True)
        elif ev == "stats":
            last.update(p)
            print(f"[gate] gate={p['gateCalls']} register={p['registerCalls']} "
                  f"lookup={p['lookupCalls']}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[gate] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    if fh and not fh.closed:
        fh.close()
    print()
    print(f"  FINAL gate={last.get('gateCalls')} register={last.get('registerCalls')} "
          f"lookup={last.get('lookupCalls')}")
    if last.get("registerCalls", 0) == 0 and last.get("gateCalls", 0) == 0:
        print("\n  The gate NEVER ran: the class map is never seeded, so the fix is to REACH it.")
    elif last.get("registerCalls", 0) == 0:
        print("\n  The gate ran but REGISTER never did: its interface lookup returns null.")
    else:
        print("\n  Registration DOES run; the gap is later than believed.")
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
