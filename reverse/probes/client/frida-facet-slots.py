#!/usr/bin/env python3
"""Do the live local-player entity's components have CLIENT FACETS bound?

WHY THIS EXISTS
===============
The open movement blocker is "the client-side facets for the local player are not created"
(`position_facets_absent_on_the_live_entity_20261012`). That entry lists the facets it could
not find by GUID, but never measured the one thing that separates two very different
investigations:

  * if NO component on the live entity has a facet bound, the local player gets no client
    facets AT ALL and the fault is in the general facet-creation path; or
  * if most have one and only the position family does not, the fault is specific to that
    family's creator.

WHERE THE SLOT IS
=================
`reverse/probes/client/frida-player-components-full.py` and the atlas. Client facets are built
by per-class by-name factories against the reflection registry global `_DAT_14a313ff8`:

    lVar = RuntimeClassRegistry::CreateByName(registry, name, size, align, ...);
    <OWNER> + 0x80 = <ctor>(lVar);      // the facet, cached on its owner
    <facet> + 0x08 = <OWNER>;           // back pointer

That is the body of `FUN_145c209f0` (PositionInTheWorldComponentClientFacet) and of the other
368 `*ComponentClientFacet` factories. So `<component> + 0x80` is the facet slot and reading it
is a pure memory read — no client code is executed except the already-proven vtable slot-0
type-id getter used by the existing component probe.

WHAT IT REPORTS, per component of the live local-player entity:
  * the component's own type GUID (vtable slot 0);
  * `[component + 0x80]`, classified as: null | unreadable | object (readable, vtable in a
    readable non-code range) | suspicious;
  * the candidate facet's own type GUID when it resolves, so a facet can be NAMED offline.

Read-only. It never writes to the target and never calls a function pointer that the existing
probe does not already call.

Usage:
  python az.py probe frida-facet-slots --timeout 300
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from _paths import probe_capture

LOOKUP = 0x1413FB700  # component lookup by AZ type id; args[0] IS an entity

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const codeRanges = mod.enumerateRanges('r-x');
  const dataRanges = mod.enumerateRanges('r--');
  const MIN_COMPONENTS = %MIN%;
  const MAX_ENTITIES = 8;
  const SLOT = 0x80;

  let lookups = 0;
  const entities = new Map();

  function inRanges(p, ranges) {
    for (let i = 0; i < ranges.length; i++) {
      const r = ranges[i];
      if (p.compare(r.base) >= 0 && p.compare(r.base.add(r.size)) < 0) return true;
    }
    return false;
  }
  const inCode = (p) => inRanges(p, codeRanges);
  const inData = (p) => inRanges(p, dataRanges);

  function fmt(p) {
    const b = new Uint8Array(p.readByteArray(16));
    const h = Array.from(b).map((x) => ('0' + x.toString(16)).slice(-2)).join('');
    return (h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' +
            h.slice(16, 20) + '-' + h.slice(20)).toUpperCase();
  }

  function compCount(p) {
    try {
      const b = p.add(0x10).readPointer();
      const e = p.add(0x18).readPointer();
      if (b.isNull() || e.isNull()) return 0;
      const n = e.sub(b).toInt32();
      if (n < 8 || n % 8 !== 0 || n > (1 << 20)) return 0;
      return n / 8;
    } catch (x) { return 0; }
  }

  Interceptor.attach(rva(0x1413fb700), {
    onEnter(args) {
      lookups++;
      try {
        const c = compCount(args[0]);
        if (c < MIN_COMPONENTS) return;
        const k = args[0].toString();
        let e = entities.get(k);
        if (!e) {
          if (entities.size >= MAX_ENTITIES) return;
          e = { count: c, hits: 0 };
          entities.set(k, e);
        }
        e.hits++;
        if (c > e.count) e.count = c;
      } catch (x) {}
    },
  });

  function typeGuid(obj) {
    try {
      const vtbl = obj.readPointer();
      if (vtbl.isNull()) return null;
      const fn = vtbl.readPointer();
      if (fn.isNull() || !inCode(fn)) return null;
      const tp = new NativeFunction(fn, 'pointer', ['pointer'])(obj);
      if (tp.isNull()) return null;
      return fmt(tp);
    } catch (e) { return null; }
  }

  // Classify the value at component + 0x80 without executing anything on it.
  function classifyFacet(p) {
    if (p.isNull()) return { kind: 'null' };
    let vtbl;
    try { vtbl = p.readPointer(); } catch (e) { return { kind: 'unreadable' }; }
    if (vtbl.isNull()) return { kind: 'suspicious', why: 'null vtable' };
    if (!inData(vtbl) && !inCode(vtbl)) {
      return { kind: 'suspicious', why: 'vtable not in a readable data/code range' };
    }
    let slot0 = null;
    try { slot0 = vtbl.readPointer(); } catch (e) {}
    const entry = {
      kind: 'object',
      ptr: p.toString(),
      vtbl: vtbl.toString(),
      slot0InCode: slot0 !== null && !slot0.isNull() && inCode(slot0),
    };
    // A facet of a component is itself an AZ reflected object: its slot-0 type-id
    // getter answers with the same GUID kind the component probe reads.
    const g = typeGuid(p);
    if (g) entry.guid = g;
    return entry;
  }

  function dump(entityPtr) {
    let begin, end;
    try {
      begin = entityPtr.add(0x10).readPointer();
      end = entityPtr.add(0x18).readPointer();
    } catch (e) { return { error: 'list read: ' + String(e) }; }
    if (begin.isNull() || end.isNull()) return { error: 'null list' };
    const d = end.sub(begin).toInt32();
    if (d < 8 || d % 8 !== 0 || d > (1 << 20)) return { error: 'bad size ' + d };
    const n = d / 8;
    const rows = [];
    const tally = { null: 0, unreadable: 0, object: 0, suspicious: 0, noComponent: 0 };
    const bad = { nullComp: 0, badVtblPtr: 0, badSlot0: 0, nullType: 0, exc: 0 };
    for (let i = 0; i < n; i++) {
      let comp, compGuid = null;
      try {
        comp = begin.add(i * 8).readPointer();
        if (comp.isNull()) { bad.nullComp++; tally.noComponent++; continue; }
        const vtbl = comp.readPointer();
        if (vtbl.isNull()) { bad.badVtblPtr++; tally.noComponent++; continue; }
        const fn = vtbl.readPointer();
        if (fn.isNull() || !inCode(fn)) { bad.badSlot0++; tally.noComponent++; continue; }
        const tp = new NativeFunction(fn, 'pointer', ['pointer'])(comp);
        if (tp.isNull()) { bad.nullType++; tally.noComponent++; continue; }
        compGuid = fmt(tp);
      } catch (e) { bad.exc++; tally.noComponent++; continue; }

      let slot = null;
      try { slot = comp.add(SLOT).readPointer(); } catch (e) {
        rows.push({ i: i, comp: comp.toString(), guid: compGuid, facet: { kind: 'unreadable' } });
        tally.unreadable++;
        continue;
      }
      const f = classifyFacet(slot);
      tally[f.kind] = (tally[f.kind] || 0) + 1;
      rows.push({ i: i, comp: comp.toString(), guid: compGuid, facet: f });
    }
    return { count: n, slotOffset: SLOT, tally: tally, bad: bad, rows: rows };
  }

  rpc.exports = {
    stats() {
      return { lookups: lookups,
               entities: Array.from(entities.entries()).map(
                 ([k, e]) => ({ address: k, count: e.count, hits: e.hits })) };
    },
    dump() {
      let best = null, bestHits = -1;
      for (const [k, e] of entities.entries()) if (e.hits > bestHits) { bestHits = e.hits; best = k; }
      if (best === null) return { error: 'no entity tracked yet' };
      return { entity: best, hits: entities.get(best).hits, ...dump(ptr(best)) };
    },
    // Required for a non-kill shutdown: this probe hooks the HOT component lookup,
    // which is what makes a bare detach crash the client (see _paths.safe_shutdown).
    teardown() { try { Interceptor.detachAll(); return true; } catch (e) { return String(e); } },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--min-components", type=int, default=100)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--shutdown", choices=["kill", "detach"], default="kill",
                    help="kill (default) ends the client deliberately and avoids the "
                         "frida-agent unload race; detach attempts an orderly teardown")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS.replace("%MIN%", str(args.min_components)))
    script.on("message", lambda m, d: print("[fs]", json.dumps(m), flush=True))
    script.load()
    print(f"[fs] attached to {args.process}", flush=True)

    capture = probe_capture(f"facet-slots-{int(time.time())}.jsonl")
    print(f"[fs] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    done = False
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end and not done:
            try:
                st = script.exports_sync.stats()
                if st.get("entities"):
                    print(f"[fs] entities={json.dumps(st['entities'])} lookups={st['lookups']}",
                          flush=True)
                    d = script.exports_sync.dump()
                    fh.write(json.dumps({"t": time.time(), "dump": d}) + "\n")
                    fh.flush()
                    if d.get("error"):
                        print(f"[fs] dump error: {d['error']}", flush=True)
                    else:
                        print(f"[fs] entity={d['entity']} components={d['count']} "
                              f"tally={json.dumps(d['tally'])}", flush=True)
                        named = 0
                        for row in d["rows"]:
                            f = row["facet"]
                            if f["kind"] == "object":
                                named += 1
                                print(f"[fs]   [{row['i']:3d}] comp={row['guid']} "
                                      f"facet=+{hex(d['slotOffset'])}->{f.get('guid', '?')}",
                                      flush=True)
                        print(f"[fs] components with a bound facet object: {named}/{d['count']}",
                              flush=True)
                        done = True
            except Exception as exc:  # noqa: BLE001
                print(f"[fs] status error: {exc}", flush=True)
                time.sleep(2.0)
                continue
            time.sleep(args.poll)

    strategy = safe_shutdown(session, script, kill=(args.shutdown == "kill"), device=device,
                             log=lambda m: print(f"[fs] {m}", flush=True))
    print(f"[fs] shutdown strategy: {strategy}", flush=True)
    print(f"[fs] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
