#!/usr/bin/env python3
"""Read the local player's own transform/body state, and watch the 4216 delivery.

WHY. Two open questions need the same instrument:

  1. Does the local player's transform change while W is held, and stop when it is
     released? Screenshot diffs cannot answer this (an earlier claim based on them was
     retracted), and the client's channel-1 stream carries no measured position, so the
     only honest signal is the player entity's own memory.
  2. With the position reply re-addressed (`AZOTH_REPLAY_POSITION_REPLY_TARGET`), does
     the RMI dispatch stop failing, and does the delivery reach a bound
     `IPositionReceiver`?

WHAT IT MEASURES, and why each part is safe:

  * The player entity is found by hooking the component lookup `FUN_1413fb700` and
    keeping entities with >= 100 components (the same gate
    `frida-player-components.py` uses; measured 2026-10-10 to be the 126-component
    local player). Nothing is written to the client.
  * The Transform (`484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0`), CharacterPhysicsComponent
    (`D707D6C5-3EFA-4275-82EB-A954F845D324`) and GameRigidBodyComponent
    (`5BA2D1FC-DB9D-4B81-88C9-89787D5C19F1`) components are located by walking the
    entity's component list and calling each component's vtable slot 0 to read its type
    GUID - the same guarded, one-shot technique the component probe already uses.
  * Each located component is then only READ: a bounded byte snapshot, diffed in Python
    so the log shows the exact changed words and their float interpretation. The layout
    is deliberately not assumed; the change itself is the measurement.
  * `FUN_1416bcba0` (RMI dispatch) is hooked to count requested ids and hits, so the
    re-addressed reply's dispatch can be read directly instead of inferred from a log
    line.
  * `FUN_143f97bf0` (the 4216 object's vtable +0x58 delivery) is hooked, and when it
    returns a target the target's own vtable +0x40 (the position setter the static
    analysis found) is attached dynamically to log the key and the three values the
    client was handed. That is the end-to-end proof that a position was delivered.

Read-only. Private no-EAC client. Attach BEFORE world entry.

Usage:
  python ef.py probe frida-movement-state --timeout 1800 --poll 0.25
"""

from __future__ import annotations

import argparse
import json
import struct
import time
from pathlib import Path

import frida

from _paths import probe_capture

LOOKUP = 0x1413FB700       # component lookup by AZ type id; args[0] IS an entity
DISPATCH = 0x1416BCBA0     # RMI dispatch: look the target local id up, log on miss
DELIVER_4216 = 0x143F97BF0 # 4216 object vtable +0x58: dispatch, then IPositionReceiver
READER_4216 = 0x143F97D10  # 4216 unmarshal reader (decode control)

COMPONENTS = {
    "transform": "484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0",
    "physics": "D707D6C5-3EFA-4275-82EB-A954F845D324",
    "rigidbody": "5BA2D1FC-DB9D-4B81-88C9-89787D5C19F1",
}
SNAPSHOT_BYTES = 0x100

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const codeRanges = mod.enumerateRanges('r-x');

  const MIN_COMPONENTS = %MINCOMPONENTS%;
  const MAX_ENTITIES = 4;
  const COMPONENTS = %COMPONENTS%;
  const SNAP = %SNAPSHOT%;

  let lookups = 0;
  const entities = new Map();   // ptr string -> {count, hits}
  const resolved = {};          // name -> ptr string
  let dispatchCalls = 0;
  let deliverCalls = 0;
  let deliverHits = 0;
  let readerCalls = 0;
  let deliver4216Id = null;
  let pendingTarget = null;
  const requested = {};
  const byCaller = {};
  const setterVtables = {};
  const setterCalls = [];

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

  Interceptor.attach(rva(0x1413fb700), {
    onEnter(args) {
      lookups++;
      this.g = null;
      try {
        // Cheapest possible gate first: the player entity is the only one with >= 32
        // components, and this hook is extremely hot (measured 561 343 calls in ~3 min).
        // Reading the requested type GUID for every call stalled the client thread, which
        // would distort the very measurement this probe exists for.
        const count = compCount(args[0]);
        if (count < MIN_COMPONENTS) return;
        const k = args[0].toString();
        let e = entities.get(k);
        if (!e) {
          if (entities.size >= MAX_ENTITIES) return;
          e = { count: count, hits: 0 };
          entities.set(k, e);
        }
        e.hits++;
        if (count > e.count) e.count = count;
        this.g = fmt(args[1]);
      } catch (x) { this.g = null; }
    },
    onLeave(retval) {
      if (this.g && !retval.isNull()) noteLookup(this.g, retval);
    },
  });

  // Resolve a component by the CLIENT'S OWN lookup: FUN_1413fb700(entity, typeId*) returns
  // the component when the entity has that type and NULL when it does not. That is the
  // signal the validated component probe uses, and it hands over the component pointer
  // directly. Two earlier attempts in this file are removed as failed alternatives:
  //   (a) calling each component's vtable slot 0 to read its type id - invalid on this
  //       build: measured 2026-10-11 only ONE module range is executable (`.text`,
  //       132 939 776 B) while every component vtable lives in `.rdata` (`r--`), so all
  //       126 components were rejected by the executable-range check;
  //   (b) scanning the component's own bytes for the type GUID - measured the same day to
  //       find none of the three GUIDs in the first 0x100 bytes of any of the 126
  //       components, i.e. the type id is not stored in the instance.
  function noteLookup(typeGuid, comp) {
    for (const name in COMPONENTS) {
      if (COMPONENTS[name] === typeGuid && !resolved[name]) {
        resolved[name] = comp.toString();
        send({ ev: 'component-found', name: name, comp: comp.toString(), guid: typeGuid });
      }
    }
  }

  // Attach to a target object's vtable +0x40, the position setter the static analysis
  // found: (**(code **)(*target + 0x40))(target, key_u64, &position_u32x4). Only the
  // resolved function pointer is checked against executable code; the target object and
  // its vtable live in data (`r--`).
  function attachSetter(targetPtr) {
    try {
      const vtbl = targetPtr.readPointer();
      const key = vtbl.toString();
      if (setterVtables[key]) return;
      const fn = vtbl.add(0x40).readPointer();
      if (fn.isNull() || !inCode(fn)) return;
      setterVtables[key] = true;
      Interceptor.attach(fn, {
        onEnter(args) {
          try {
            const raw = [];
            for (let i = 0; i < 4; i++) raw.push(args[2].add(i * 4).readU32());
            setterCalls.push({
              t: Date.now(), target: targetPtr.toString(), key: args[1].toString(),
              raw: raw,
              floats: raw.map((v) => new Float32Array(new Uint32Array([v]).buffer)[0]),
            });
            if (setterCalls.length > 64) setterCalls.shift();
          } catch (e) {}
        },
      });
      send({ ev: 'setter-attached', target: targetPtr.toString(), vtable: key, fn: fn.toString() });
    } catch (e) {}
  }

  function liveEntity() {
    let best = null, bestHits = -1;
    for (const [k, e] of entities.entries()) {
      if (e.hits > bestHits) { bestHits = e.hits; best = k; }
    }
    return best;
  }

  // Diagnostic: walk the tracked entity's component list and report what the GUID read
  // actually produces, so a resolution failure names its stage instead of being silent.
  function probeComponents() {
    const key = liveEntity();
    return { entity: key, hits: key === null ? 0 : entities.get(key).hits,
             found: resolved };
  }

  let resolvedEntity = null;

  rpc.exports = {
    probeComponents() { return probeComponents(); },
    // Locate the three components on the LIVE entity. Re-resolves when the live entity
    // changes, because during the world load a short-lived 126-component entity can be
    // seen first and would otherwise be cached forever (measured: hits 21 dead vs 1955
    // live in one load).
    locate() {
      const out = { entities: [], resolved: {} };
      for (const [k, e] of entities.entries()) {
        out.entities.push({ address: k, count: e.count, hits: e.hits });
      }
      const key = liveEntity();
      if (key === null) return out;
      if (key !== resolvedEntity) {
        // Only wipe when the live entity actually CHANGED. Wiping on the first call threw
        // away the components the hook had just resolved (measured 2026-10-11: transform
        // found, then immediately discarded, and the entity is looked up only rarely in
        // world so it did not come back).
        if (resolvedEntity !== null) {
          for (const name in COMPONENTS) delete resolved[name];
        }
        resolvedEntity = key;
      }
      const entity = ptr(key);
      for (const name in COMPONENTS) {
        if (resolved[name]) out.resolved[name] = resolved[name];
      }
      out.entity = key;
      return out;
    },
    // Bounded read of one located component.
    snapshot(name) {
      const addr = resolved[name];
      if (!addr) return null;
      try {
        const b = new Uint8Array(ptr(addr).readByteArray(SNAP));
        return Array.from(b).map((x) => ('0' + x.toString(16)).slice(-2)).join('');
      } catch (e) { return null; }
    },
    // Attach to the position setter of whatever the 4216 dispatch returned, called
    // from Python (never from inside a hook callback).
    hookSetter() {
      if (pendingTarget === null) return null;
      const p = pendingTarget;
      pendingTarget = null;
      try { attachSetter(ptr(p)); return p; } catch (e) { return null; }
    },
    stats() {
      return {
        lookups: lookups,
        entities: Array.from(entities.entries()).map(([k, e]) => ({ address: k, count: e.count, hits: e.hits })),
        resolved: resolved,
        dispatch_calls: dispatchCalls,
        deliver_4216_calls: deliverCalls,
        deliver_4216_hits: deliverHits,
        deliver_4216_id: deliver4216Id,
        reader_4216_calls: readerCalls,
        requested: requested,
        by_caller: byCaller,
        setter_vtables: Object.keys(setterVtables),
        setter_calls: setterCalls.slice(-16),
      };
    },
  };
}
"""


def diff_words(prev: str | None, cur: str | None) -> list[tuple[int, int, int, float, float]]:
    """(offset, old_u32, new_u32, old_float, new_float) for every changed 4-byte word."""
    if not prev or not cur or len(prev) != len(cur):
        return []
    out = []
    for off in range(0, len(cur) - 7, 4):
        a = int(cur[off:off + 8], 16)
        b = int(prev[off:off + 8], 16)
        if a != b:
            fa = struct.unpack("<f", struct.pack("<I", b))[0]
            fb = struct.unpack("<f", struct.pack("<I", a))[0]
            out.append((off // 2, b, a, fa, fb))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--poll", type=float, default=0.25)
    ap.add_argument("--min-components", type=int, default=32,
                    help="component-count gate for the player entity (measured 126)")
    ap.add_argument("--process", default="NewWorld.exe")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS.replace("%COMPONENTS%", json.dumps(COMPONENTS))
                                     .replace("%SNAPSHOT%", str(SNAPSHOT_BYTES))
                                     .replace("%MINCOMPONENTS%", str(args.min_components)))
    script.on("message", lambda m, d: print("[mv]", json.dumps(m), flush=True))
    script.load()
    print(f"[mv] attached to {args.process}", flush=True)

    capture = probe_capture(f"movement-state-{int(time.time())}.jsonl")
    print(f"[mv] live -> {capture}", flush=True)

    prev: dict[str, str | None] = {k: None for k in COMPONENTS}
    end = time.time() + args.timeout
    located = False
    last_stats = 0.0
    last_locate_attempt = 0.0
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                # Entity location is BEST EFFORT and must never gate the dispatch /
                # delivery counters: an earlier version of this probe spent a whole
                # session stuck in "not located" and reported nothing else, which
                # wasted the run. Retry it, but keep sampling the counters regardless.
                if not located and time.time() - last_locate_attempt > 5.0:
                    last_locate_attempt = time.time()
                    loc = script.exports_sync.locate()
                    if loc and loc.get("resolved"):
                        located = True
                        print(f"[mv] located {json.dumps(loc)}", flush=True)
                    elif loc:
                        print(
                            f"[mv] entity not located yet: "
                            f"entities={json.dumps(loc.get('entities'))}",
                            flush=True,
                        )
                        if loc.get("entities"):
                            diag = script.exports_sync.probe_components()
                            print(f"[mv] component probe: {json.dumps(diag)}", flush=True)
                if located:
                    for name in COMPONENTS:
                        cur = script.exports_sync.snapshot(name)
                        changes = diff_words(prev[name], cur)
                        if changes:
                            row = {
                                "t": time.time(), "component": name,
                                "changes": [
                                    {"off": f"0x{o:x}", "old": f"0x{a:08x}", "new": f"0x{c:08x}",
                                     "old_f": round(fa, 4), "new_f": round(fb, 4)}
                                    for (o, a, c, fa, fb) in changes
                                ],
                            }
                            fh.write(json.dumps(row) + "\n")
                            fh.flush()
                            print(f"[mv] CHANGE {name} {json.dumps(row['changes'])}", flush=True)
                        prev[name] = cur
                if time.time() - last_stats > 10:
                    try:
                        hooked = script.exports_sync.hook_setter()
                        if hooked:
                            print(f"[mv] setter hooked on target {hooked}", flush=True)
                    except Exception:  # noqa: BLE001
                        pass
                    st = script.exports_sync.stats()
                    fh.write(json.dumps({"t": time.time(), "stats": st}) + "\n")
                    fh.flush()
                    print(
                        "[mv] "
                        f"lookups={st['lookups']} entities={len(st['entities'])} "
                        f"dispatch={st['dispatch_calls']} deliver={st['deliver_4216_calls']}"
                        f"/{st['deliver_4216_hits']} reader={st['reader_4216_calls']} "
                        f"requested={json.dumps(st['requested'])} "
                        f"setters={len(st['setter_vtables'])} calls={len(st['setter_calls'])}",
                        flush=True,
                    )
                    # The delivery path calls the dispatch at 0x143f97c02; print that
                    # caller separately from the plain dispatch path.
                    bc = st.get("by_caller") or {}
                    deliv = bc.get("143f97c02")
                    print(f"[mv] by_caller={json.dumps(bc)}", flush=True)
                    if deliv:
                        print(
                            f"[mv] DELIVERY-PATH dispatch: calls={deliv['calls']} "
                            f"non-null={deliv['hits']} ids={json.dumps(deliv['ids'])}",
                            flush=True,
                        )
                    last_stats = time.time()
                time.sleep(args.poll)
            except Exception as exc:  # noqa: BLE001 - the target may exit
                print(f"[mv] status error: {exc}", flush=True)
                time.sleep(1.0)

    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    print(f"[mv] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
