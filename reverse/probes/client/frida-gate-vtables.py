#!/usr/bin/env python3
"""Dump the vtable of the slice-job objects the Transform gate dispatches through.

WHY. `FUN_141763b70` (the gate) does, for each slice job:

    lVar10 = param_1->vtable[+0x20](param_1, FUN_1407fbe80());   // asks for {83482F97-...}
    if (lVar10 != 0) FUN_141582430(lVar10, ...);                 // the ONLY GameTransformComponent inserter

A live count (probe `frida-transform-gate`) shows the gate running **30 times** with 30 distinct job
pointers and `FUN_141582430` being called **0 times**. So the query at `+0x20` returns null for all 30.

An earlier static attempt read the slot table that follows the `{83482F97-...}` GUID and concluded the
interface was stubbed. That was a CATEGORY ERROR: that descriptor supplies the type id the gate PASSES
IN; the function the gate CALLS lives in the JOB's vtable. This probe measures the job's vtable directly,
which is the only way to answer it, and it needs no alignment guess.

For each distinct job pointer it reports the vtable address and every slot in the first 8, so the slot at
`+0x20` can be disassembled and compared across all 30 jobs. If they all share one vtable, the answer is
one function; if they differ, the answer is per-job.

Read-only. Ends through `device.kill` (it hooks code the client runs continuously).

Usage:
  python ef.py probe frida-gate-vtables --wait 400 --timeout 200
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

GATE = 0x141763B70
REGISTER = 0x141582430

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);

  const seen = {};
  let gateCalls = 0, registerCalls = 0;

  Interceptor.attach(rva(%GATE%), {
    onEnter(args) {
      gateCalls++;
      const job = args[0];
      if (job.isNull()) { send({ev:'gate-null-arg'}); return; }
      let key;
      try { key = job.toString(); } catch (e) { return; }
      if (seen[key]) return;
      seen[key] = true;

      let vt = null, slots = [];
      try {
        vt = job.readPointer();
        for (let i = 0; i < 8; i++) {
          slots.push(vt.add(i * Process.pointerSize).readPointer().toString());
        }
      } catch (e) {
        send({ ev: 'job-dump-error', job: key, error: String(e) });
        return;
      }
      send({ ev: 'job', job: key, vtable: vt.toString(), slots: slots });
    }
  });

  try {
    Interceptor.attach(rva(%REGISTER%), { onEnter() { registerCalls++; } });
  } catch (e) { send({ev:'attach-error', error:String(e)}); }

  send({ ev: 'ready', base: base.toString(16) });
  setInterval(() => {
    send({ ev: 'stats', gateCalls: gateCalls, registerCalls: registerCalls,
           distinctJobs: Object.keys(seen).length });
  }, 5000);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=200)
    args = ap.parse_args()

    source = (JS.replace("%GATE%", hex(GATE)).replace("%REGISTER%", hex(REGISTER)))
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
        print("[vt] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    out = probe_capture(f"gate-vtables-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")
    vtables: dict[str, list[str]] = {}
    last: dict = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[vt] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        if fh and not fh.closed:
            fh.write(json.dumps(p) + "\n")
            fh.flush()
        ev = p.get("ev")
        if ev == "ready":
            print(f"[vt] attached base={p['base']}", flush=True)
        elif ev == "job":
            vtables.setdefault(p["vtable"], []).append(p["job"])
            print(f"[vt] job {p['job']} vtable={p['vtable']} +0x20={p['slots'][4]}", flush=True)
        elif ev == "stats":
            last.update(p)
            print(f"[vt] gate={p['gateCalls']} register={p['registerCalls']} "
                  f"distinctJobs={p['distinctJobs']}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[vt] live pid={pid} -> {out}", flush=True)

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
          f"distinctJobs={last.get('distinctJobs')}")
    print(f"  distinct JOB vtables: {len(vtables)}")
    for vt, jobs in vtables.items():
        print(f"    {vt}  ({len(jobs)} jobs)")
    if len(vtables) == 1:
        print("\n  All jobs share ONE vtable: the +0x20 slot is a single function to inspect.")
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
