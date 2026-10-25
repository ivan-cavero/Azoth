#!/usr/bin/env python3
"""Full, named component list of the live local-player entity, plus targeted probes.

WHY. Two earlier probes answered part of this and both had a bug worth recording:
`frida-player-components.py --mode getters` and my own `frida-movement-state.py` rejected
every component by checking `inCode(vtable)` before calling it. On this build that check is
wrong: the component's VTABLE lives in `.rdata` (`r--`) while the FUNCTION POINTER stored in
it lives in `.text`. The correct check is on the resolved function pointer, not on the vtable.
Result of the bug: 126/126 components reported as `badVtbl`, which is why the component
resolution kept "failing" for no real reason.

WHAT THIS DOES, all read-only:
  1. hooks the component lookup `FUN_1413fb700(entity, typeId*)`, tracks the entity with the
     most lookups AND >= N components (measured: the live player entity has 126; a
     short-lived one appears first with the same count but ~20 hits, so hits break the tie);
  2. dumps EVERY component of that entity: each component's type GUID, read by calling
     vtable slot 0 (the AZ type-id getter) with the CORRECT code check;
  3. calls the client's OWN lookup `FUN_1413fb700` with a candidate list, so presence/absence
     of specific components (physics, position, camera) is a direct answer from the client
     rather than a string guess.

Naming of the dumped GUIDs is done offline against `research/atlas/az-type-registry.json`.

Usage:
  python ef.py probe frida-player-components-full --timeout 900 --poll 5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from _paths import probe_capture, safe_shutdown

LOOKUP = 0x1413FB700   # component lookup by AZ type id; args[0] IS an entity

# Candidate components to ask the client about directly. GUID text form as the registry uses
# it; the probe converts to the raw 16 bytes the lookup expects.
CANDIDATES = {
    "Transform": "484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0",
    "CharacterComponent": "15407CAA-4970-4D06-8B5C-612FBA11BB45",
    "CharacterPhysicsComponent": "D707D6C5-3EFA-4275-82EB-A954F845D324",
    "GameRigidBodyComponent": "5BA2D1FC-DB9D-4B81-88C9-89787D5C19F1",
    "PlayerPositionTrackingComponent": "62620B33-6F37-418B-9C4F-62AD6058D54D",
    "PlayerPositionTrackingComponentClientFacet": "B74D06BC-123E-4C39-A842-EB8CDE4B6DAF",
    "PlayerPositionTrackingComponentServerFacet": "7A014FFD-A6FD-418F-ABF0-2EBD64B6785D",
    "PositionInTheWorldComponentClientFacet": "E496F4B6-65ED-409D-ADA5-201E14B27B9D",
    "PositionInTheWorldComponentServerFacet": "BAD06625-69F1-4275-8331-11361D041574",
    "PositionalTicketingComponentClientFacet": "782B7389-541E-48EA-8A70-68A8BB010745",
    "PositionalTicketingComponentServerFacet": "8432A24F-CFAA-40D5-BBBE-FE8245936F8C",
    "CameraComponent": "E409F5C0-9919-4CA5-9488-1FE8A041768E",
    "CameraStateComponentClientFacet": "6142325B-50AF-4F07-9F72-7F08FC727EDB",
    "PersistentPositionInTheWorldData": "8420DAFA-5389-4AFC-9F0B-7F5472C334D4",
    "IPositionReceiver": "17C00FC6-074F-47EB-9640-9743D890ED6F",
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

  let lookups = 0;
  const entities = new Map();
  const CANDIDATES = %CANDIDATES%;

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
          e = { count: c, hits: 0 };
          entities.set(k, e);
        }
        e.hits++;
        if (c > e.count) e.count = c;
      } catch (x) {}
    },
  });

  // Dump every component's type GUID. The vtable lives in .rdata, the slot-0 function pointer
  // lives in .text: check the POINTER, never the vtable (the bug in the earlier probes).
  function dumpComponents(entityPtr) {
    let begin, end;
    try {
      begin = entityPtr.add(0x10).readPointer();
      end = entityPtr.add(0x18).readPointer();
    } catch (e) { return { error: 'list read: ' + String(e) }; }
    if (begin.isNull() || end.isNull()) return { error: 'null list' };
    const d = end.sub(begin).toInt32();
    if (d < 8 || d % 8 !== 0 || d > 1 << 20) return { error: 'bad size ' + d };
    const n = d / 8;
    const out = [], bad = { nullComp: 0, badVtblPtr: 0, badSlot0: 0, nullType: 0, exc: 0 };
    for (let i = 0; i < n; i++) {
      try {
        const comp = begin.add(i * 8).readPointer();
        if (comp.isNull()) { bad.nullComp++; continue; }
        const vtbl = comp.readPointer();
        if (vtbl.isNull()) { bad.badVtblPtr++; continue; }
        const fn = vtbl.readPointer();
        if (fn.isNull() || !inCode(fn)) { bad.badSlot0++; continue; }
        const tp = new NativeFunction(fn, 'pointer', ['pointer'])(comp);
        if (tp.isNull()) { bad.nullType++; continue; }
        out.push({ i: i, comp: comp.toString(), guid: fmt(tp) });
      } catch (e) { bad.exc++; }
    }
    return { count: n, resolved: out.length, guids: out, bad: bad };
  }

  function guidBytes(text) {
    const hex = text.replace(/-/g, '');
    const b = [];
    for (let i = 0; i < 16; i++) b.push(parseInt(hex.substr(i * 2, 2), 16));
    return b;
  }

  // The registry's GUID text form and the raw 16 bytes the lookup expects may differ by the
  // standard little-endian GUID field swap. Trying both removes a whole class of false
  // "not found" results; the probe reports which layout matched.
  function guidBytesLE(text) {
    const b = guidBytes(text);
    const swap = (arr, off, n) => { for (let i = 0; i < n / 2; i++) { const t = arr[off + i]; arr[off + i] = arr[off + n - 1 - i]; arr[off + n - 1 - i] = t; } };
    swap(b, 0, 4); swap(b, 4, 2); swap(b, 6, 2);
    return b;
  }

  // Ask the CLIENT's own lookup whether this entity has each candidate component.
  function probeCandidates(entityPtr) {
    const res = {};
    for (const name in CANDIDATES) {
      const entry = { guid: CANDIDATES[name] };
      for (const [layout, bytes] of [['text', guidBytes(CANDIDATES[name])],
                                     ['le', guidBytesLE(CANDIDATES[name])]]) {
        try {
          const buf = Memory.alloc(16);
          buf.writeByteArray(bytes);
          const p = new NativeFunction(rva(0x1413fb700), 'pointer', ['pointer', 'pointer'])(entityPtr, buf);
          if (!p.isNull()) {
            entry.found = true;
            entry.layout = layout;
            entry.ptr = p.toString();
            break;
          }
          entry.found = false;
        } catch (e) { entry.error = String(e); }
      }
      res[name] = entry;
    }
    return res;
  }

  rpc.exports = {
    stats() {
      return { lookups: lookups,
               entities: Array.from(entities.entries()).map(([k, e]) => ({ address: k, count: e.count, hits: e.hits })) };
    },
    dump() {
      const key = liveEntity();
      if (key === null) return { error: 'no entity tracked yet' };
      return { entity: key, hits: entities.get(key).hits, ...dumpComponents(ptr(key)) };
    },
    candidates() {
      const key = liveEntity();
      if (key === null) return { error: 'no entity tracked yet' };
      return { entity: key, results: probeCandidates(ptr(key)) };
    },
    // Required for a non-kill shutdown: this probe hooks the HOT component lookup,
    // which is what makes a bare detach crash the client (see _paths.safe_shutdown).
    teardown() { try { Interceptor.detachAll(); return true; } catch (e) { return String(e); } },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--min-components", type=int, default=100)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--shutdown", choices=["kill", "detach"], default="kill",
                    help="kill (default) ends the client deliberately and avoids the "
                         "frida-agent unload race; detach attempts an orderly teardown")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(
        JS.replace("%CANDIDATES%", json.dumps(CANDIDATES))
          .replace("%MIN%", str(args.min_components))
    )
    script.on("message", lambda m, d: print("[pc]", json.dumps(m), flush=True))
    script.load()
    print(f"[pc] attached to {args.process}", flush=True)

    capture = probe_capture(f"player-components-full-{int(time.time())}.jsonl")
    print(f"[pc] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    done_dump = done_cand = False
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                st = script.exports_sync.stats()
                if st.get("entities"):
                    print(f"[pc] entities={json.dumps(st['entities'])} lookups={st['lookups']}", flush=True)
                if st.get("entities") and not done_dump:
                    d = script.exports_sync.dump()
                    fh.write(json.dumps({"t": time.time(), "dump": d}) + "\n")
                    fh.flush()
                    print(f"[pc] DUMP entity={d.get('entity')} count={d.get('count')} "
                          f"resolved={d.get('resolved')} bad={json.dumps(d.get('bad'))}", flush=True)
                    for row in d.get("guids") or []:
                        print(f"[pc]   [{row['i']:3d}] {row['guid']}  {row['comp']}", flush=True)
                    done_dump = bool(d.get("resolved"))
                if st.get("entities") and not done_cand:
                    c = script.exports_sync.candidates()
                    fh.write(json.dumps({"t": time.time(), "candidates": c}) + "\n")
                    fh.flush()
                    for name, r in (c.get("results") or {}).items():
                        print(f"[pc] CAND {name:48s} found={r.get('found')} "
                              f"layout={r.get('layout')} {r.get('error', '')}", flush=True)
                    done_cand = True
                if done_dump and done_cand:
                    print("[pc] both passes done", flush=True)
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"[pc] status error: {exc}", flush=True)
                time.sleep(2.0)
                continue
            time.sleep(args.poll)

    safe_shutdown(session, script, kill=(args.shutdown == "kill"), device=device,
                  log=lambda m: print(f"[pc] {m}", flush=True))
    print(f"[pc] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
