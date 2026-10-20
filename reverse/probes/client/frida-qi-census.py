#!/usr/bin/env python3
"""Does ANY slice job answer the Transform query? Challenge the 'impossible' conclusion.

WHY. The session's conclusion was that `remoteplayer.dynamicslice` can never get a
`GameTransformComponent` in this build: the gate `FUN_141763b70` runs 30 times, `FUN_141582430`
registers 0 times, and the slice job's QueryInterface returns null for `{83482F97-…}`.

But the operator can SEE NPCs in the world (named ones: "ELRIC", "Saradnax"), and those are
`remoteplayer.dynamicslice` instances from the capture. So either:
  * some jobs DO answer the query and get a real Transform (and the 26 nulls are the other ones), or
  * those visible bodies come from a different path entirely (they are actors the client created
    from the spawn record before any of this, and never go through the gate).

That distinction decides whether item 1 is truly closed or whether there is a subset of objects that
work - and if a subset works, the job is to make the created entity join that subset.

WHAT THIS PROBE DOES. Hooks the QueryInterface (RVA 0x1445390) and, for the Transform GUID only,
records the RESULT per distinct object, plus the gate's own call count. If every object returns null,
the conclusion stands. If some return non-null, they are named here.

Read-only. Ends through `device.kill` (hooks hot code).

Usage:
  python az.py probe frida-qi-census --wait 400 --timeout 240
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

QI = 0x141445390
GATE = 0x141763B70
WANTED = "83482f9784da4fd4bf9e7fe34c8e091f"

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const wanted = %WANTED%;

  const perObject = {};   // self -> {calls, nonNull}
  let wantedCalls = 0, wantedNonNull = 0, gateCalls = 0;
  const guidsSeen = {};

  function hexOf(ptr) {
    try {
      const b = new Uint8Array(ptr.readByteArray(16));
      let h = '';
      for (let i = 0; i < 16; i++) h += ('0' + b[i].toString(16)).slice(-2);
      return h;
    } catch (e) { return null; }
  }

  Interceptor.attach(rva(%QI%), {
    onEnter(args) {
      this.self = args[0];
      this.guid = hexOf(args[1]);
      if (this.guid) guidsSeen[this.guid] = (guidsSeen[this.guid] || 0) + 1;
      this.want = (this.guid === wanted);
    },
    onLeave(ret) {
      if (!this.want) return;
      wantedCalls++;
      const key = this.self.toString();
      if (!perObject[key]) perObject[key] = {calls: 0, nonNull: 0};
      perObject[key].calls++;
      if (!ret.isNull()) {
        wantedNonNull++;
        perObject[key].nonNull++;
      }
    }
  });

  try { Interceptor.attach(rva(%GATE%), { onEnter() { gateCalls++; } }); } catch (e) {}

  send({ ev: 'ready', base: base.toString(16) });
  setInterval(() => {
    send({ ev: 'stats', wantedCalls: wantedCalls, wantedNonNull: wantedNonNull,
           gateCalls: gateCalls, objects: Object.keys(perObject).length,
           guidsSeen: guidsSeen, perObject: perObject });
  }, 5000);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    source = (JS.replace("%QI%", hex(QI)).replace("%GATE%", hex(GATE))
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
        print("[census] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    out = probe_capture(f"qi-census-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")
    last: dict = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[census] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        if fh and not fh.closed:
            fh.write(json.dumps(p) + "\n")
            fh.flush()
        if p.get("ev") == "ready":
            print(f"[census] attached base={p['base']}", flush=True)
        elif p.get("ev") == "stats":
            last.update(p)
            print(f"[census] wantedCalls={p['wantedCalls']} nonNull={p['wantedNonNull']} "
                  f"gate={p['gateCalls']} objects={p['objects']}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[census] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    if fh and not fh.closed:
        fh.close()
    print()
    print(f"  FINAL wantedCalls={last.get('wantedCalls')} nonNull={last.get('wantedNonNull')} "
          f"gate={last.get('gateCalls')} objects={last.get('objects')}")
    po = last.get("perObject", {})
    ok = {k: v for k, v in po.items() if v.get("nonNull")}
    print(f"  objects that ANSWERED the Transform query: {len(ok)}")
    for k, v in list(ok.items())[:8]:
        print(f"    {k}  calls={v['calls']} nonNull={v['nonNull']}")
    if not ok and last.get("wantedCalls"):
        print("\n  Every object returned null: the 'impossible' conclusion stands.")
    elif ok:
        print("\n  SOME objects answer it. Those are the ones to study and join.")
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
