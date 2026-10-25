#!/usr/bin/env python3
"""Find the LOCAL RMI target id of a named client facet in THIS session.

WHY THIS EXISTS
===============
The red HUD cable is the ALC's `javelin.alc-server-timeout-for-input`, i.e. the client is
waiting for the server to answer its input stream (wire `0x635`,
`ActionListComponentServerFacet_ReceiveInputFromClient`, ~20/s). The capture shows the real
server answering that burst immediately with `0x1096` / `0x1097`
(`TimeComponentClientFacet_SyncTimeChange` / `SyncDayPhase`), and those two messages carry a
**16-byte target**:

    seq 117  00 01 96 42  93a3e477cb5fd51e bf85314bbc4a951a  <payload>
    seq 118  00 01 97 42  93a3e477cb5fd51e bf85314bbc4a951a  00000002

Our server replays those bodies verbatim, and the client rejects them with
`RMIDispatch: The facet target ID couldn't be found {targetLocalId: 10638597947943539998}` -
i.e. `0x93a3e477cb5fd51e`, the first half of that blob. So the target id in the capture is the
**capture's session** id, and the client's own registry assigns a different one in our session.
(Cross-check: `TimeComponentClientFacet` IS bound in our session - measured at
`component + 0x80` on component 65 - so the facet exists; only its local id differs.)

This probe reads the client's own RMI target registry (the same one
`frida-position-target.py` walks), resolves each distinct target's AZ type GUID through its
vtable slot 0, and prints the local ids per type name. That turns "address the reply to the
right facet" from a guess into a lookup.

Registry layout, measured: `registry + 0x148` is the map; `map + 0x40` = capacity,
`map + 0x50` = sentinel, `map + 0x68` = entries (0x10 bytes each, key u64 at +0);
`registry + 0x1b0` = object vector, object pointer at `+i*0x10 + 8`.

Read-only: one vtable call per DISTINCT vtable (the same AZ type-id getter the component
probe already uses), not per target.

Usage:
  python ef.py probe frida-facet-target-id --find TimeComponentClientFacet
  python ef.py probe frida-facet-target-id                # dump every facet id
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

DISPATCH = 0x1416BCBA0  # RMI dispatch; args[1] is the registry

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const codeRanges = mod.enumerateRanges('r-x');
  let registry = null;

  function inCode(p) {
    for (let i = 0; i < codeRanges.length; i++) {
      const r = codeRanges[i];
      if (p.compare(r.base) >= 0 && p.compare(r.base.add(r.size)) < 0) return true;
    }
    return false;
  }

  // Learn the registry pointer from the client's own dispatch, so we do not have to hardcode
  // a global that moves between builds.
  Interceptor.attach(rva(0x1416bcba0), {
    onEnter(args) { try { registry = args[1]; } catch (e) {} },
  });

  function fmt(p) {
    const b = new Uint8Array(p.readByteArray(16));
    const h = Array.from(b).map((x) => ('0' + x.toString(16)).slice(-2)).join('');
    return (h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' +
            h.slice(16, 20) + '-' + h.slice(20)).toUpperCase();
  }

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

  rpc.exports = {
    scan() {
      const targets = readTargets();
      if (targets === null) return { error: 'registry not learned yet (no dispatch seen)' };
      // Resolve the type GUID once per distinct vtable, then report ids per GUID.
      const byVtable = new Map();
      for (const t of targets) {
        let k;
        try { k = t.obj.readPointer().toString(); } catch (e) { continue; }
        if (!byVtable.has(k)) byVtable.set(k, { guid: typeGuid(t.obj), ids: [] });
        byVtable.get(k).ids.push(t.id);
      }
      const byGuid = {};
      for (const [, e] of byVtable.entries()) {
        if (!e.guid) continue;
        if (!byGuid[e.guid]) byGuid[e.guid] = [];
        for (const id of e.ids) if (byGuid[e.guid].length < 40) byGuid[e.guid].push(id);
      }
      return {
        targets: targets.length,
        distinct_vtables: byVtable.size,
        guids: Object.keys(byGuid).length,
        by_guid: byGuid,
        registry: registry.toString(),
      };
    },
    teardown() { try { Interceptor.detachAll(); return true; } catch (e) { return String(e); } },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--find", default="", help="only report types whose NAME contains this")
    ap.add_argument("--publish", default="",
                    help="write the first local id found for a type whose name contains this "
                         "to --publish-to, so the world server can re-address its reply")
    ap.add_argument("--publish-to", default=".azoth/state/alc-target.txt")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--poll", type=float, default=4.0)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--shutdown", choices=["kill", "detach"], default="kill")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[ft]", json.dumps(m), flush=True))
    script.load()
    print(f"[ft] attached to {args.process}", flush=True)

    capture = probe_capture(f"facet-target-id-{int(time.time())}.jsonl")
    print(f"[ft] live -> {capture}", flush=True)

    # Names come from the AZ registry, so a GUID can be turned into a class name offline.
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    reg = json.loads((root / "research" / "atlas" / "az-type-registry.json")
                     .read_text(encoding="utf-8"))["types"]
    by_guid = {t["guid"].upper(): t["name"] for t in reg}

    end = time.time() + args.timeout
    done = False
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end and not done:
            try:
                res = script.exports_sync.scan()
            except Exception as exc:  # noqa: BLE001
                print(f"[ft] scan error: {exc}", flush=True)
                time.sleep(2.0)
                continue
            if res.get("error"):
                print(f"[ft] {res['error']}", flush=True)
                time.sleep(args.poll)
                continue
            fh.write(json.dumps({"t": time.time(), "scan": res}) + "\n")
            fh.flush()
            print(f"[ft] targets={res['targets']} distinct_vtables={res['distinct_vtables']} "
                  f"named_guids={res['guids']}", flush=True)
            named = 0
            published = None
            for guid, ids in sorted(res["by_guid"].items()):
                name = by_guid.get(guid)
                if not name:
                    continue
                named += 1
                # Exact name match only. A substring match is not safe here: asking for
                # `TimeComponentClientFacet` also matches `PlayerTimeComponentClientFacet`,
                # and the first hit won - which published the wrong facet's id once.
                if args.publish and name.lower() == args.publish.lower() and published is None:
                    published = (name, ids[0] if ids else None)
                if args.find and args.find.lower() not in name.lower():
                    continue
                print(f"[ft]   {name:52} ids={json.dumps(ids[:6])}", flush=True)
            print(f"[ft] resolved {named} distinct facet types", flush=True)

            if args.publish:
                if published and published[1]:
                    target = Path(args.publish_to)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(published[1] + "\n", encoding="utf-8")
                    print(f"[ft] PUBLISHED {published[0]} -> {published[1]} "
                          f"({target})", flush=True)
                else:
                    print(f"[ft] publish: no local id found for {args.publish!r}",
                          flush=True)
            done = True

    strategy = safe_shutdown(session, script, kill=(args.shutdown == "kill"), device=device,
                             log=lambda m: print(f"[ft] {m}", flush=True))
    print(f"[ft] shutdown strategy: {strategy}", flush=True)
    print(f"[ft] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
