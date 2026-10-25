#!/usr/bin/env python3
"""Which RMI target local ids does the client actually have registered?

WHY. Measured 2026-10-11: with `MF_RELIABLE` set, `ReceivePlayerPositionClientMsg`
(wire 4216) decodes and its reader runs, but every application attempt logs

    RMIDispatch: The facet target ID couldn't be found when trying to dispatch
    the RMI message. {"targetLocalId":1915519389091857855, ...}

Static analysis of that log line's own function (`FUN_1416bcba0`, the only
reference to the string at `0x148041db0`) shows the lookup:

    map = registry + 0x148          ; open-addressing hash map, FNV-1a over 8 key bytes
    key = *(u64 *)(message + 8)     ; the target local id from the wire
    index = map_find(map, key)      ; FUN_1417da460
    target = *(u64 *)(*(registry + 0x1b0) + index * 0x10 + 8)
    if (not found) log "facet target ID couldn't be found"; return 0

So the client is asking for a target it does not have. This probe answers the
only question that decides the fix: **what does the registry contain, is the id the
server sends (`0x1A954ABC4B3185BF`) among them, and does any registered target
implement `IPositionReceiver`?** A target whose vtable is the 4216 object vtable
`0x1482ea3e8` is flagged, because that is the object whose slot +0x58 performs the
position delivery; seeing which ids the registry maps to which vtables is what turns
"the target is missing" into a concrete choice of target id.

MEASURED 2026-10-11 (live, one session): capacity 131072, 37063 registered keys.
`1a954abc4b3185bf` (the actor id the server sends): 601 lookups, 0 hits. The blob the
capture's own input-response messages carry (`93a3e477cb5fd51e`): 136 lookups, 136
hits. So `facet target ID couldn't be found` is a wrong-target problem, not a
missing facet type.

Map layout read from `FUN_1417da460` (byte-verified decompile):
  +0x28 secondary hash, +0x30 flag, +0x40 capacity, +0x50 empty-slot sentinel,
  +0x68 entries base, stride 0x10 = {u64 key, u64 value}.

Read-only. Private no-EAC client.

Usage:
  python ef.py probe frida-rmi-targets --timeout 900 --poll 5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from _paths import probe_capture

DISPATCH = 0x1416BCBA0      # RMI dispatch: look the target local id up, log on miss
DELIVER_4216 = 0x143F97BF0  # 4216 object vtable +0x58: dispatch then IPositionReceiver
IFACE_GUID = 0x143FB2B90    # returns the interface GUID the delivery looks up

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);

  let registry = null;          // last registry object seen by the dispatcher
  let dispatchCalls = 0;
  let deliverCalls = 0;
  const requested = {};         // id hex -> {calls, hits}
  const lastRequested = [];

  try {
    Interceptor.attach(rva(0x1416bcba0), {
      onEnter(args) {
        dispatchCalls++;
        this.msg = args[0];
        this.reg = args[1];
        try {
          registry = args[1];
          const id = args[0].add(8).readU64().toString(16).padStart(16, '0');
          this.id = id;
          if (!(id in requested)) {
            requested[id] = { calls: 0, hits: 0 };
            if (lastRequested.length < 24) lastRequested.push(id);
          }
          requested[id].calls++;
        } catch (e) { this.id = null; }
      },
      onLeave(retval) {
        if (this.id && requested[this.id] && !retval.isNull()) requested[this.id].hits++;
      },
    });
  } catch (e) { send({ ev: 'error', hook: 'dispatch', error: String(e) }); }

  try {
    Interceptor.attach(rva(0x143f97bf0), {
      onEnter(args) { deliverCalls++; this.msg = args[0]; },
    });
  } catch (e) { send({ ev: 'error', hook: 'deliver4216', error: String(e) }); }

  function dumpRegistry() {
    if (registry === null || registry.isNull()) return null;
    try {
      const map = registry.add(0x148);
      const capacity = map.add(0x40).readU64().toNumber();
      const sentinel = map.add(0x50).readU64();
      const entries = map.add(0x68).readPointer();
      const vecBase = registry.add(0x1b0).readPointer();
      const vecSize = registry.add(0x188).readU64().toNumber();
      const keys = [];
      const wanted = {};
      if (capacity > 0 && capacity < 0x100000) {
        for (let i = 0; i < capacity; i++) {
          try {
            const key = entries.add(i * 0x10).readU64();
            if (key.equals(sentinel)) continue;
            const val = entries.add(i * 0x10 + 8).readU64().toNumber();
            // The map is key-only: FUN_1417da460 never reads entry+8. The find returns
            // the SLOT index, and FUN_1416bcba0 indexes the parallel array at
            // registry+0x1b0 by that slot (stride 0x10, object pointer at +8).
            let target = '0x0';
            let vtable = '0x0';
            let is4216 = false;
            try {
              const tp = vecBase.add(i * 0x10 + 8).readPointer();
              target = tp.toString();
              vtable = tp.readPointer().toString();
              is4216 = tp.readPointer().equals(rva(0x1482ea3e8));
            } catch (e) {}
            const hex = key.toString(16).padStart(16, '0');
            keys.push({ slot: i, id: hex, val: val, target: target, vtable: vtable, pos4216: is4216 });
            if (hex in requested) {
              wanted[hex] = { slot: i, target: target, vtable: vtable, pos4216: is4216 };
            }
          } catch (e) { break; }
        }
      }
      return { capacity: capacity, vec_size: vecSize, keys: keys, requested_found: wanted };
    } catch (e) { return { error: String(e) }; }
  }

  rpc.exports = {
    snapshot() {
      return {
        dispatch_calls: dispatchCalls,
        deliver_4216_calls: deliverCalls,
        registry: registry === null ? null : registry.toString(),
        requested: requested,
        requested_order: lastRequested,
        map: dumpRegistry(),
      };
    },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--process", default="NewWorld.exe")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[rmi]", json.dumps(m), flush=True))
    script.load()
    print(f"[rmi] attached to {args.process}", flush=True)

    capture = probe_capture(f"rmi-targets-{int(time.time())}.jsonl")
    print(f"[rmi] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    last_keys = None
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                st = script.exports_sync.snapshot()
            except Exception as exc:  # noqa: BLE001 - the target may exit
                print(f"[rmi] status error: {exc}", flush=True)
                time.sleep(args.poll)
                continue
            fh.write(json.dumps(st) + "\n")
            fh.flush()
            m = st.get("map") or {}
            keys = m.get("keys") or []
            summary = {
                "dispatch": st.get("dispatch_calls"),
                "deliver4216": st.get("deliver_4216_calls"),
                "capacity": m.get("capacity"),
                "registered": len(keys),
                "requested": {
                    k: v for k, v in (st.get("requested") or {}).items()
                },
                "requested_found": m.get("requested_found"),
            }
            print(f"[rmi] {json.dumps(summary)}", flush=True)
            if keys != last_keys:
                for row in keys:
                    flag = "  <-- 4216 IPositionReceiver object" if row.get("pos4216") else ""
                    print(f"[rmi] target slot={row['slot']} id={row['id']} obj={row['target']} "
                          f"vtable={row.get('vtable')}{flag}", flush=True)
                last_keys = keys
            time.sleep(args.poll)

    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    print(f"[rmi] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
