#!/usr/bin/env python3
"""Settle the physics-component disagreement: three snapshots of one entity, plus every ADD.

WHY. Two records disagree about the live local-player entity, using the same method:
`local_player_components_step0_20261010` says the client's lookup `FUN_1413fb700` FOUND
`CharacterPhysicsComponent` and `GameRigidBodyComponent` on the 126-component player entity;
`physics_components_absent_on_the_live_player_entity_20261012` measured the opposite on the
same entity. The 2026-10-12 measurement was a SINGLE instant ~4 s after spawn and the client
died ~3 s later, so it cannot distinguish "the entity never has physics" from "the entity gets
physics later".

THIS PROBE ANSWERS THAT, with one session and no ambiguity:

  * it hooks `FUN_1413789c0` (the component ADD) and logs EVERY add: which entity, which
    component, and the component's AZ type GUID read through vtable slot 0. A late physics
    addition therefore cannot be missed;
  * it takes THREE snapshots of the SAME entity (the one with the most lookups, which is the
    live player): the first as soon as it is tracked, then at +30 s and +120 s. Each snapshot
    lists all component GUIDs AND asks the client's own lookup for the two physics GUIDs
    directly, trying both GUID byte orders;
  * it reports the component count at each instant, so a change in count is visible.

METHOD NOTE that this probe depends on: a component's VTABLE lives in `.rdata` (`r--`) while
the function pointer stored in it lives in `.text`. Checking `inCode(vtable)` rejects every
component. Check the resolved FUNCTION POINTER. That bug is why earlier runs reported 126/126
`badVtbl`.

Attach at CHARACTER SELECT (after the splash gate, before Play), then click Play: the entity is
only looked up during the world load, and attaching during the title phase has crashed the
client.

Usage:
  python az.py probe frida-physics-timeline --timeout 900 --snap2 30 --snap3 120
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from _paths import probe_capture

LOOKUP = 0x1413FB700   # component lookup by AZ type id; args[0] IS an entity
ADD = 0x1413789C0      # append component to an entity; args[0] entity, args[1] component

PHYSICS = {
    "CharacterPhysicsComponent": "D707D6C5-3EFA-4275-82EB-A954F845D324",
    "GameRigidBodyComponent": "5BA2D1FC-DB9D-4B81-88C9-89787D5C19F1",
    # controls: these must be present, or the entity we are reading is not the player
    "Transform": "484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0",
    "CharacterComponent": "15407CAA-4970-4D06-8B5C-612FBA11BB45",
    "PlayerPositionTrackingComponent": "62620B33-6F37-418B-9C4F-62AD6058D54D",
}

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const codeRanges = mod.enumerateRanges('r-x');
  const MIN_COMPONENTS = %MIN%;
  const MAX_ENTITIES = 8;
  const CANDIDATES = %CANDIDATES%;
  const MAX_ADDS = 4000;

  let lookups = 0, adds = 0, addsSkipped = 0;
  const entities = new Map();
  const addLog = [];

  function inCode(p) {
    for (let i = 0; i < codeRanges.length; i++) {
      const r = codeRanges[i];
      if (p.compare(r.base) >= 0 && p.compare(r.base.add(r.size)) < 0) return true;
    }
    return false;
  }

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
      if (n < 8 || n % 8 !== 0 || n > 1 << 20) return 0;
      return n / 8;
    } catch (x) { return 0; }
  }

  function guidOf(comp) {
    try {
      const vtbl = comp.readPointer();
      if (vtbl.isNull()) return null;
      const fn = vtbl.readPointer();
      if (fn.isNull() || !inCode(fn)) return null;
      const tp = new NativeFunction(fn, 'pointer', ['pointer'])(comp);
      if (tp.isNull()) return null;
      return fmt(tp);
    } catch (e) { return null; }
  }

  function liveEntity() {
    let best = null, bestHits = -1;
    for (const [k, e] of entities.entries()) {
      if (e.hits > bestHits) { bestHits = e.hits; best = k; }
    }
    return best;
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
          e = { count: c, hits: 0, firstSeen: Date.now() };
          entities.set(k, e);
        }
        e.hits++;
        if (c > e.count) e.count = c;
      } catch (x) {}
    },
  });

  // Every ADD, with the entity and the added component's type GUID. This is the part that
  // cannot miss a late physics component.
  Interceptor.attach(rva(0x1413789c0), {
    onEnter(args) {
      adds++;
      try {
        const ent = args[0], comp = args[1];
        const g = guidOf(comp);
        const k = ent.toString();
        const rec = { t: Date.now(), entity: k, guid: g, entityCount: compCount(ent) };
        if (addLog.length < MAX_ADDS) addLog.push(rec);
        else addsSkipped++;
        if (g) send({ ev: 'add', entity: k, guid: g, count: rec.entityCount });
      } catch (e) {}
    },
  });

  function dumpEntity(entityPtr) {
    let begin, end;
    try {
      begin = entityPtr.add(0x10).readPointer();
      end = entityPtr.add(0x18).readPointer();
    } catch (e) { return { error: 'list read: ' + String(e) }; }
    if (begin.isNull() || end.isNull()) return { error: 'null list' };
    const d = end.sub(begin).toInt32();
    if (d < 8 || d % 8 !== 0 || d > 1 << 20) return { error: 'bad size ' + d };
    const n = d / 8;
    const guids = [], bad = { nullComp: 0, badVtblPtr: 0, badSlot0: 0, nullType: 0, exc: 0 };
    for (let i = 0; i < n; i++) {
      try {
        const comp = begin.add(i * 8).readPointer();
        if (comp.isNull()) { bad.nullComp++; continue; }
        const g = guidOf(comp);
        if (g === null) { bad.exc++; continue; }
        guids.push(g);
      } catch (e) { bad.exc++; }
    }
    return { count: n, resolved: guids.length, guids: guids, bad: bad };
  }

  function guidBytes(text) {
    const hex = text.replace(/-/g, '');
    const b = [];
    for (let i = 0; i < 16; i++) b.push(parseInt(hex.substr(i * 2, 2), 16));
    return b;
  }
  function guidBytesLE(text) {
    const b = guidBytes(text);
    const swap = (arr, off, n) => { for (let i = 0; i < n / 2; i++) { const t = arr[off + i]; arr[off + i] = arr[off + n - 1 - i]; arr[off + n - 1 - i] = t; } };
    swap(b, 0, 4); swap(b, 4, 2); swap(b, 6, 2);
    return b;
  }

  function askClient(entityPtr) {
    const res = {};
    for (const name in CANDIDATES) {
      const entry = { guid: CANDIDATES[name], found: false };
      for (const [layout, bytes] of [['text', guidBytes(CANDIDATES[name])],
                                     ['le', guidBytesLE(CANDIDATES[name])]]) {
        try {
          const buf = Memory.alloc(16);
          buf.writeByteArray(bytes);
          const p = new NativeFunction(rva(0x1413fb700), 'pointer', ['pointer', 'pointer'])(entityPtr, buf);
          if (!p.isNull()) { entry.found = true; entry.layout = layout; entry.ptr = p.toString(); break; }
        } catch (e) { entry.error = String(e); }
      }
      res[name] = entry;
    }
    return res;
  }

  rpc.exports = {
    stats() {
      return { lookups: lookups, adds: adds, adds_skipped: addsSkipped,
               entities: Array.from(entities.entries()).map(([k, e]) => ({ address: k, count: e.count, hits: e.hits })) };
    },
    // One snapshot: the full component list plus the client's own answer for each candidate.
    snapshot() {
      const key = liveEntity();
      if (key === null) return { error: 'no entity tracked yet' };
      const e = entities.get(key);
      return {
        entity: key, hits: e.hits, first_seen_ms: e.firstSeen,
        dump: dumpEntity(ptr(key)),
        asked: askClient(ptr(key)),
        adds_total: adds,
      };
    },
    adds() { return { total: adds, skipped: addsSkipped, log: addLog.slice(-200) }; },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--poll", type=float, default=3.0)
    ap.add_argument("--snap2", type=float, default=30.0, help="seconds after snapshot 1")
    ap.add_argument("--snap3", type=float, default=120.0, help="seconds after snapshot 1")
    ap.add_argument("--min-components", type=int, default=100)
    ap.add_argument("--process", default="NewWorld.exe")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.process)
    script = session.create_script(
        JS.replace("%CANDIDATES%", json.dumps(PHYSICS))
          .replace("%MIN%", str(args.min_components))
    )
    script.on("message", lambda m, d: print("[pt]", json.dumps(m), flush=True))
    script.load()
    print(f"[pt] attached to {args.process}", flush=True)

    capture = probe_capture(f"physics-timeline-{int(time.time())}.jsonl")
    print(f"[pt] live -> {capture}", flush=True)

    def report(tag: str, snap: dict, fh) -> None:
        dump = snap.get("dump") or {}
        guids = dump.get("guids") or []
        print(f"[pt] ===== {tag} entity={snap.get('entity')} count={dump.get('count')} "
              f"resolved={dump.get('resolved')} bad={json.dumps(dump.get('bad'))} "
              f"adds_total={snap.get('adds_total')}", flush=True)
        for name, r in (snap.get("asked") or {}).items():
            print(f"[pt]   ASK {name:34s} found={r.get('found')} layout={r.get('layout')}", flush=True)
        for name, g in PHYSICS.items():
            print(f"[pt]   LIST {name:34s} present={g in guids}", flush=True)
        fh.write(json.dumps({"t": time.time(), "tag": tag, **snap}) + "\n")
        fh.flush()

    end = time.time() + args.timeout
    t_first = None
    done2 = done3 = False
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                st = script.exports_sync.stats()
                if st.get("entities") and t_first is None:
                    snap = script.exports_sync.snapshot()
                    if snap.get("entity"):
                        t_first = time.time()
                        report("snapshot-1 (as soon as tracked)", snap, fh)
                elif t_first is not None:
                    elapsed = time.time() - t_first
                    if not done2 and elapsed >= args.snap2:
                        report(f"snapshot-2 (+{args.snap2:.0f}s)", script.exports_sync.snapshot(), fh)
                        done2 = True
                    if not done3 and elapsed >= args.snap3:
                        report(f"snapshot-3 (+{args.snap3:.0f}s)", script.exports_sync.snapshot(), fh)
                        done3 = True
                        # final: the whole add log
                        a = script.exports_sync.adds()
                        fh.write(json.dumps({"t": time.time(), "adds": a}) + "\n")
                        fh.flush()
                        print(f"[pt] adds total={a['total']} skipped={a['skipped']}", flush=True)
                        print(f"[pt] adds (last 200) -> {json.dumps(a['log'][-200:])[:2000]}", flush=True)
                        break
                else:
                    print(f"[pt] waiting for the world load; lookups={st.get('lookups')} "
                          f"adds={st.get('adds')}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[pt] status error: {exc}", flush=True)
                time.sleep(2.0)
                continue
            time.sleep(args.poll)

    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    print(f"[pt] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
