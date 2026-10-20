#!/usr/bin/env python3
"""Which entities does the client actually resolve components on, and does any hold a known actor?

WHY THIS EXISTS, and why it is not a memory scan. The 2026-10-20 census showed that only 4 of the 12
actor ids the capture declares are present in client memory, and that no id sits next to a world
position - so the entities that RENDER are not findable by id. The roadmap's named instrument was the
entity table at `this+0x110`; a first attempt at walking it guessed the bucket/chain layout and
walked into code memory (measured: `comps=112` at a `.text` address), so that layout is NOT documented
and guessing it produced garbage rather than a result.

THIS PROBE USES A MEASURED ANCHOR INSTEAD. `FUN_1413fb700(entity, typeId*)` is the client's own
component lookup, its `args[0]` IS an entity, and the component list at `entity+0x10`/`entity+0x18` is
a vector of pointers (count = (end-begin)/8, must be a multiple of 8) - both measured in
`player_entity_component_list_measured_20261012`, where the live local player came back with **126**
components. So hooking that function enumerates the entities the client genuinely resolves, which is a
stronger answer than any hash-table guess.

WHAT IT REPORTS, per distinct entity, all read-only:
  * how many components it has, and how many lookups it saw (the live player is the one with ~126 and
    the most hits; a short-lived entity appears first with the same count and few hits);
  * whether any of the 12 declared actor ids appears in the entity's first 0x200 bytes - this is the
    question the census could not answer, because an entity may hold its actor id at an offset;
  * the `Transform` component from the client's own lookup, hexdumped, plus any world coordinate pair
    found in its first 0x200 bytes in EITHER endianness (a native struct holds floats
    little-endian, while the wire is big-endian - the first version of the census missed every pair
    by only looking at the wire order).

NO UNLOAD AT THE END: `frida-agent.dll_unloaded` execute-after-unload is a measured crash source here
(offset 0x9c7e0). The session stays attached and the client is ended with `python az.py stop`.

Usage:
  python az.py probe frida-entity-walk --seconds 30
"""

from __future__ import annotations

import argparse
import json
import time

import frida

LOOKUP = 0x1413FB700  # component lookup by AZ type id; args[0] IS an entity

# The 12 actor ids the capture's remoteplayer.dynamicslice instances declare, plus the local
# player's (the positive control). Extracted from the committed replay with decode_bundle.
ACTORS = {
    "player": "1a954abc4b3185bfbe37c3d8592618e0",
    "rid29": "3c757da5b2549230fdd559012f5bb05e",
    "rid30": "e2917c2cb9fb4ed3f1018cef205f6686",
    "rid60": "e440562ddc204f7f8cb013ceb696fff4",
    "rid79": "fe77eefa932f9c7c9d784a8f6f4430ef",
    "rid87": "5eeaa6572a88a3bee0488cb4dcb9895e",
    "rid88": "4c48151bfa86ffbb33c823cd6d9c1479",
    "rid89": "c229bb14a86d25cc50f115381df53b7d",
    "rid90": "84515ae9909636e95f2d6df3d0440c0e",
    "rid91": "dcf7ff88ddb9cbf893ffa94f3f130a9d",
    "rid92": "c0f655ce4e0991da5d38262dee3c5290",
    "rid93": "9c5c7eb3e469380ea1a41cf482316a35",
    "rid94": "8e4972fff4e9b510fb6ebae832f27c59",
}
TRANSFORM = "484ae67dabd04d9cb2c89bb0eec900e0"
# From research/atlas/az-type-registry.json by NAME (not by index - index 18 in the player's own
# component list is a different component; the registry is the authority for the GUID).
# MEASURED 2026-10-20: writing the simulation Transform does NOT move the rendered body, and the
# player's own component list includes this render-side component, so it is the next one to resolve.
RENDER_TRANSFORM = "8bd9b27a088b4f36b97fc0b479615755"

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) { send({ ev: 'error', error: 'NewWorld.exe not found' }); }
else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const MAX_ENTITIES = %MAX_ENTITIES%;
  const MIN_COMPONENTS = %MIN_COMPONENTS%;
  const ENTITY_BYTES = 0x200;
  // MEASURED 2026-10-20: the world position sits at +0xE48 in a remote entity's Transform, so a
  // 0x400-byte window reports 'no position' for every entity - a window bug, not a negative.
  const TRANSFORM_BYTES = 0x4000;
  const DUMP = %DUMP%;
  const ACTORS = %ACTORS%;
  const transformId = Memory.alloc(16);
  const TX = %TRANSFORM%;
  for (let i = 0; i < 16; i++) transformId.add(i).writeU8(TX[i]);
  const renderId = Memory.alloc(16);
  const RX = %RENDER_TRANSFORM%;
  for (let i = 0; i < 16; i++) renderId.add(i).writeU8(RX[i]);

  const lookup = new NativeFunction(rva(0x1413fb700), 'pointer', ['pointer', 'pointer']);
  const entities = new Map();
  let lookups = 0, skipped = 0;

  function compCount(p) {
    // MEASURED (player_entity_component_list_measured_20261012): entity+0x10/+0x18 is a vector of
    // component pointers, so the count is the byte delta / 8 and must divide evenly.
    try {
      const b = p.add(0x10).readPointer();
      const e = p.add(0x18).readPointer();
      if (b.isNull() || e.isNull()) return 0;
      const n = e.sub(b).toInt32();
      if (n < 8 || n % 8 !== 0 || n > 1 << 20) return 0;
      return n / 8;
    } catch (x) { return 0; }
  }

  function bytesToHex(buf) {
    const u8 = new Uint8Array(buf);
    let out = '';
    for (let i = 0; i < u8.length; i++) out += u8[i].toString(16).padStart(2, '0');
    return out;
  }

  function actorIdsIn(p) {
    const found = [];
    let hex = null;
    try { hex = bytesToHex(p.readByteArray(ENTITY_BYTES)); } catch (e) { return found; }
    if (hex === null) return found;
    for (const name in ACTORS) {
      const at = hex.indexOf(ACTORS[name]);
      if (at >= 0) found.push({ name: name, byteOffset: at / 2 });
    }
    return found;
  }

  function worldPairs(buf) {
    const dv = new DataView(buf);
    const out = [];
    for (let o = 0; o + 8 <= buf.byteLength; o += 4) {
      const xb = dv.getFloat32(o, false), yb = dv.getFloat32(o + 4, false);
      if (xb > 9000 && xb < 9700 && yb > 2500 && yb < 3000) out.push({ off: o, order: 'be', x: +xb.toFixed(2), y: +yb.toFixed(2) });
      const xl = dv.getFloat32(o, true), yl = dv.getFloat32(o + 4, true);
      if (xl > 9000 && xl < 9700 && yl > 2500 && yl < 3000) out.push({ off: o, order: 'le', x: +xl.toFixed(2), y: +yl.toFixed(2) });
      if (out.length >= 6) break;
    }
    return out;
  }

  Interceptor.attach(rva(0x1413fb700), {
    onEnter(args) {
      lookups++;
      try {
        const c = compCount(args[0]);
        // MEASURED 2026-10-20: with no floor, 457k lookups in 12 s filled the map with 400 objects
        // of 1-7 components - the lookup is called for far more than entities. The live local
        // player has **126** components (`player_entity_component_list_measured_20261012`), so a
        // floor is what separates a character from the noise.
        if (c < MIN_COMPONENTS) return;
        const k = args[0].toString();
        let e = entities.get(k);
        if (!e) {
          if (entities.size >= MAX_ENTITIES) { skipped++; return; }
          e = { count: c, hits: 0, last: 0 };
          entities.set(k, e);
        }
        e.hits++;
        e.last = Date.now();
        if (c > e.count) e.count = c;
      } catch (x) {}
    },
  });

  function report() {
    const rows = [];
    const now = Date.now();
    for (const [k, e] of entities.entries()) {
      // Only touch entities seen in the last 6 s: a freed heap pointer reads as garbage, and this
      // project has already paid once for reading an entity that was gone.
      const fresh = (now - e.last) < 6000;
      const row = { at: k, comps: e.count, hits: e.hits, fresh: fresh };
      const p = ptr(k);
      if (!fresh) { rows.push(row); continue; }
      row.actors = actorIdsIn(p);
      if (DUMP) { try { row.entityHex = bytesToHex(p.readByteArray(ENTITY_BYTES)); } catch (x) {} }
      try {
        const t = lookup(p, transformId);
        if (!t.isNull()) {
          row.transform = t.toString();
          // THE MEASURED LAYOUT (2026-10-20): the world position is x at +0x14c, y at +0x15c, z at
          // +0x16c - stride 0x10, NOT the 12-byte contiguous triple every earlier scan searched for,
          // which is why none of them ever found it. Confirmed by calling the client's own accessor
          // FUN_140fddfa0, whose holder IS a Transform component (type 484AE67D-...).
          try {
            row.pos = [+t.add(0x14c).readFloat().toFixed(4),
                        +t.add(0x15c).readFloat().toFixed(4),
                        +t.add(0x16c).readFloat().toFixed(4)];
          } catch (e) { row.posError = String(e).slice(0, 60); }
          const buf = t.readByteArray(TRANSFORM_BYTES);
          if (buf !== null) {
            row.transformPairs = worldPairs(buf);
            if (DUMP) row.transformHex = bytesToHex(buf);
          }
        }
        // THE RENDER-SIDE COMPONENT: does it exist on these entities, and does it hold the position?
        const r = lookup(p, renderId);
        if (!r.isNull()) {
          row.renderTransform = r.toString();
          try {
            row.renderPos = [+r.add(0x14c).readFloat().toFixed(4),
                             +r.add(0x15c).readFloat().toFixed(4),
                             +r.add(0x16c).readFloat().toFixed(4)];
          } catch (e) { }
          const rbuf = r.readByteArray(TRANSFORM_BYTES);
          if (rbuf !== null) {
            row.renderPairs = worldPairs(rbuf);
            if (DUMP) row.renderHex = bytesToHex(rbuf);
          }
        }
      } catch (x) { row.lookupError = String(x).slice(0, 100); }
      rows.push(row);
    }
    rows.sort((a, b) => b.comps - a.comps);
    send({ ev: 'report', lookups: lookups, entities: rows.length, skipped: skipped, rows: rows });
  }

  setInterval(report, 5000);
  send({ ev: 'probe-ready' });
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=40,
                    help="how long to observe; 0 = until the job is stopped (recommended: the client "
                         "is loading while the probe must stay attached)")
    ap.add_argument("--max-entities", type=int, default=400)
    ap.add_argument("--dump", action="store_true", help="include raw hex of each entity and transform")
    ap.add_argument("--min-components", type=int, default=40,
                    help="component-count floor; the live local player has 126, props have 1-7")
    args = ap.parse_args()

    source = (
        JS.replace("%MAX_ENTITIES%", str(args.max_entities))
        .replace("%ACTORS%", json.dumps(ACTORS))
        .replace("%TRANSFORM%", json.dumps(list(bytes.fromhex(TRANSFORM))))
        .replace("%RENDER_TRANSFORM%", json.dumps(list(bytes.fromhex(RENDER_TRANSFORM))))
        .replace("%DUMP%", "true" if args.dump else "false")
        .replace("%MIN_COMPONENTS%", str(args.min_components))
    )

    device = frida.get_local_device()
    pid = next((p.pid for p in device.enumerate_processes()
                if p.name.lower() == "newworld.exe"), None)
    if pid is None:
        print("[walk] no NewWorld.exe running")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    latest: dict = {}
    reports = 0

    def on_message(message, _data):
        nonlocal reports
        if message.get("type") != "send":
            print("[walk] err:", str(message.get("description"))[:200], flush=True)
            return
        payload = message["payload"]
        if payload.get("ev") == "error":
            print("[walk] script error:", payload.get("error"), flush=True)
            return
        if payload.get("ev") != "report":
            return
        reports += 1
        latest.clear()
        latest.update(payload)
        # PERSIST ON EVERY REPORT. A Frida agent that unloads kills this client
        # (frida-agent.dll_unloaded, offset 0x9c7e0, reproduced repeatedly on 2026-10-20), so the
        # numbers must be on disk before the process can die - never only at the end.
        try:
            with open(".azoth/state/entity-walk.json", "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except OSError:
            pass
        print(f"[walk] report #{reports} lookups={payload['lookups']} "
              f"entities={payload['entities']} skipped={payload['skipped']}", flush=True)

    script.on("message", on_message)
    script.load()
    span = "until stopped" if args.seconds <= 0 else f"{args.seconds}s"
    print(f"[walk] attached pid={pid}; observing {span}", flush=True)

    end = None if args.seconds <= 0 else time.time() + args.seconds
    while end is None or time.time() < end:
        time.sleep(1)

    rows = latest.get("rows") or []
    print(f"\n{'entity':20s} {'comps':>6s} {'hits':>7s}  {'actor ids in first 0x200':38s} transform")
    for row in rows:
        actors = ",".join(f"{a['name']}@{a['byteOffset']:#x}" for a in row.get("actors") or [])
        print(f"{row['at']:20s} {row['comps']:6d} {row['hits']:7d}  {actors[:38]:38s} "
              f"{row.get('transform') or '-'}")

    with_transform = [r for r in rows if r.get("transform")]
    print(f"\nentities with a resolved Transform: {len(with_transform)} of {len(rows)}")
    for row in with_transform:
        pairs = row.get("transformPairs") or []
        if pairs:
            print(f"  {row['at']} pairs in transform: {pairs}")

    out = ".azoth/state/entity-walk.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(latest, handle, indent=2)
    print(f"\n[walk] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
