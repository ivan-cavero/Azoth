#!/usr/bin/env python3
"""Which registered RMI target actually implements IPositionReceiver?

WHY. Measured 2026-10-11: re-addressing the position reply to the capture's own
input-response blob (`93a3e477cb5fd51e`) removes the `facet target ID couldn't be
found` failure completely (dispatch 642/642 hits, 0 facet errors for
ReceivePlayerPositionClientMsg, down from 0/601 and 13012 errors), and the delivery
path's own dispatch call succeeds 260/260. But `FUN_143f97bf0` still returns 0, so the
position is not applied:

    target = dispatch(message)                     // now succeeds
    if (target != 0) {
        q = (*target->vtable[0x20])(target, IPositionReceiver_guid)   // <-- returns 0
        if (q != 0) { (*q->vtable[0x40])(q, key, &position); return 1; }
    }
    return 0

So the remaining question is which registered target's object answers that interface
query. This probe answers it directly, using the client's own GUID getter
`FUN_143fb2b90` rather than a hand-built GUID, and grouping the 37k registered targets
by their object's vtable so the interface query is called once per distinct vtable
instead of once per target.

Read-only apart from the interface queries themselves (the same call the client makes
on this path anyway).

Usage:
  python ef.py probe frida-position-target --timeout 300 --max-vtables 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from _paths import probe_capture

DISPATCH = 0x1416BCBA0      # RMI dispatch (message -> target object)
GUID_GETTER = 0x143FB2B90   # returns the IPositionReceiver interface GUID pointer
DELIVER_4216 = 0x143F97BF0  # the delivery whose interface query we are trying to satisfy

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let registry = null;
  let deliverId = null;
  let deliverCalls = 0, deliverHits = 0;

  Interceptor.attach(rva(0x1416bcba0), {
    onEnter(args) { try { registry = args[1]; } catch (e) {} },
  });

  Interceptor.attach(rva(0x143f97bf0), {
    onEnter(args) { deliverCalls++; try { deliverId = args[0].add(8).readU64().toString(16).padStart(16, '0'); } catch (e) {} },
    onLeave(retval) { if (!retval.isNull() && retval.toInt32() !== 0) deliverHits++; },
  });

  // The client's own GUID getter: returns a pointer to the 16-byte interface GUID.
  function interfaceGuid() {
    return new NativeFunction(rva(0x143fb2b90), 'pointer', [])();
  }

  function readTargets() {
    if (registry === null || registry.isNull()) return null;
    const map = registry.add(0x148);
    const capacity = map.add(0x40).readU64().toNumber();
    const sentinel = map.add(0x50).readU64();
    const entries = map.add(0x68).readPointer();
    const vecBase = registry.add(0x1b0).readPointer();
    if (!(capacity > 0 && capacity < 0x100000)) return null;
    const out = [];
    for (let i = 0; i < capacity; i++) {
      try {
        const key = entries.add(i * 0x10).readU64();
        if (key.equals(sentinel)) continue;
        let obj = null;
        try { obj = vecBase.add(i * 0x10 + 8).readPointer(); } catch (e) { continue; }
        if (obj.isNull()) continue;
        out.push({ id: key.toString(16).padStart(16, '0'), obj: obj });
      } catch (e) { break; }
    }
    return out;
  }

  function readPtr(p) {
    try { return p.readPointer(); } catch (e) { return null; }
  }

  rpc.exports = {
    state() {
      return {
        registry: registry === null ? null : registry.toString(),
        deliver_calls: deliverCalls, deliver_hits: deliverHits, deliver_id: deliverId,
      };
    },
    // Group registered targets by their object's vtable and ask each distinct vtable
    // once whether it answers IPositionReceiver.
    scan(maxVtables) {
      const targets = readTargets();
      if (targets === null) return { error: 'no registry' };
      const guid = interfaceGuid();
      const byVtable = new Map();
      for (const t of targets) {
        const vtbl = readPtr(t.obj);
        if (vtbl === null || vtbl.isNull()) continue;
        const k = vtbl.toString();
        if (!byVtable.has(k)) byVtable.set(k, { vtable: k, ids: [], obj: t.obj });
        const e = byVtable.get(k);
        if (e.ids.length < 8) e.ids.push(t.id);
      }
      const tested = [];
      const positive = [];
      let n = 0;
      for (const [k, e] of byVtable.entries()) {
        if (n >= maxVtables) break;
        n++;
        let q = null, err = null;
        try {
          const fn = e.vtable ? ptr(k).add(0x20).readPointer() : null;
          if (fn !== null && !fn.isNull()) {
            q = new NativeFunction(fn, 'pointer', ['pointer', 'pointer'])(e.obj, guid);
          }
        } catch (ex) { err = String(ex); }
        const ok = q !== null && !q.isNull();
        const row = { vtable: k, ids: e.ids, answered: ok, interface_obj: ok ? q.toString() : null };
        if (err) row.error = err;
        tested.push(row);
        if (ok) positive.push(row);
      }
      return {
        targets: targets.length,
        distinct_vtables: byVtable.size,
        tested: n,
        positives: positive,
        sample: tested.slice(0, 40),
      };
    },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-vtables", type=int, default=600)
    ap.add_argument("--process", default="NewWorld.exe")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[pt]", json.dumps(m), flush=True))
    script.load()
    print(f"[pt] attached to {args.process}", flush=True)

    capture = probe_capture(f"position-target-{int(time.time())}.jsonl")
    print(f"[pt] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    while time.time() < end:
        try:
            st = script.exports_sync.state()
        except Exception as exc:  # noqa: BLE001
            print(f"[pt] state error: {exc}", flush=True)
            time.sleep(2.0)
            continue
        print(f"[pt] state {json.dumps(st)}", flush=True)
        if st.get("registry"):
            break
        time.sleep(2.0)

    try:
        res = script.exports_sync.scan(args.max_vtables)
    except Exception as exc:  # noqa: BLE001
        print(f"[pt] scan error: {exc}", flush=True)
        res = {"error": str(exc)}

    with capture.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(res) + "\n")
    print(f"[pt] targets={res.get('targets')} distinct_vtables={res.get('distinct_vtables')} "
          f"tested={res.get('tested')}", flush=True)
    for row in res.get("positives") or []:
        print(f"[pt] POSITIVE vtable={row['vtable']} ids={json.dumps(row['ids'])} "
              f"iface={row['interface_obj']}", flush=True)
    if not res.get("positives"):
        print("[pt] no registered target answered IPositionReceiver in the tested set", flush=True)

    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
