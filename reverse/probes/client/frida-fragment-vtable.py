#!/usr/bin/env python3
"""Read the per-fragment object's VTABLE at runtime, per record and per fragment key.

WHY. Decompiling `FUN_141717fc0` showed the record dispatcher has two structurally different
apply paths:

  * CREATION (the record's slot `state + 0x608 + record_id*0x10` is EMPTY) applies the whole
    record in one call (`FUN_14178db00`) with no per-fragment filter;
  * UPDATE (the slot already exists - every correction, because the spawn created it) loops the
    fragment vector and for EACH fragment calls a virtual function at `object->vtable + 0x60`,
    adding the fragment to the component map only when that call returns 0.

That explains why four payload shapes were accepted with zero client errors and changed nothing:
the gate is per-fragment and the server does not control it.

What could NOT be answered statically is **which vtable** the object carries: pattern-matching
`.rdata` for the `+0x60` slot value landed on a serializer (see
`fragment_object_vtable_identification_FAILED_20261018`). So read it from the live object instead.

WHAT THIS PROBE DOES. Hooks `FUN_141717fc0` on enter, walks the fragment vector it was handed, and
for each element reports the fragment key, the object pointer and its vtable pointer, plus the
resolved function at the vtable slots the dispatcher uses (`+0x60` is the update-path predicate,
`+0x90` is the reader used when the fragment is first parsed). One line per fragment per record,
with the record id, so a spawn record (48 fragments) can be told from the local-player metadata
record (9 fragments) - both are `record_id 1` and only the count separates them.

Read-only: it calls no client function and writes no client memory. Ends through
`_paths.safe_shutdown()` because a bare `detach()` after hooking a hot function was measured to
kill this client minutes later (frida-agent.dll execute-after-unload).

Usage:
  python az.py probe frida-fragment-vtable [--timeout 180] [--max-records 12]
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);

  // Vector layout, from the decompiled dispatcher: the element stride is 0x18 and the
  // element is `[u32 key][pad][object smart-ptr: object at +8, control block at +0x10]`.
  // The vector object holds its current end at +8 and its capacity end at +0x10.
  const ELEM = 0x18;

  let records = 0;

  // FUN_141717fc0(state, record_id, fragment_vector, seq, flag, ok, instance_id)
  Interceptor.attach(off(0x141717fc0), {
    onEnter(args) {
      records++;
      if (records > 400) return;
      let recordId = null, vec = null, seq = null, flag = null;
      try { recordId = args[1].toInt32() & 0xffff; } catch (e) {}
      try { vec = args[2]; } catch (e) {}
      try { seq = args[3]; } catch (e) {}
      try { flag = args[4].toInt32() & 0xff; } catch (e) {}
      if (vec === null) return;

      // Vector members, read from the decompiled writer in FUN_146af2340:
      //   +0x00 begin, +0x08 current END (advanced by 0x18 per element), +0x10 capacity end.
      let begin = null, end = null, cap = null;
      try { begin = vec.add(0x0).readPointer(); } catch (e) { return; }
      try { end = vec.add(0x8).readPointer(); } catch (e) { return; }
      try { cap = vec.add(0x10).readPointer(); } catch (e) { cap = null; }
      if (begin.isNull() || end.isNull()) return;

      const span = end.sub(begin).toInt32();
      if (span < 0 || span > 0x4000 || span % ELEM !== 0) return;
      const count = Math.floor(span / ELEM);

      const frags = [];
      for (let i = 0; i < count && i < 64; i++) {
        const el = begin.add(i * ELEM);
        let key = null, obj = null, vt = null, at60 = null, at90 = null;
        try { key = el.readU32(); } catch (e) {}
        try { obj = el.add(8).readPointer(); } catch (e) {}
        if (obj === null || obj.isNull()) continue;
        try { vt = obj.readPointer(); } catch (e) {}
        if (vt === null || vt.isNull()) continue;
        try { at60 = vt.add(0x60).readPointer(); } catch (e) {}
        try { at90 = vt.add(0x90).readPointer(); } catch (e) {}
        frags.push({
          i: i,
          key: key,
          obj: obj.toString(),
          vtable: vt.toString(),
          slot60: at60 === null ? null : at60.toString(),
          slot90: at90 === null ? null : at90.toString(),
        });
      }
      send({ev:'record', n: records, recordId: recordId, seq: seq, flag: flag,
            count: count, fragments: frags});
    }
  });
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", default="fragment-vtable.jsonl")
    parser.add_argument("--keep-process", action="store_true",
                        help="orderly detach instead of killing the client")
    args = parser.parse_args()

    out_path = probe_capture(args.out)
    device = frida.get_local_device()
    session = None
    for _ in range(90):
        try:
            session = device.attach("NewWorld.exe")
            break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    if session is None:
        raise SystemExit("could not attach to NewWorld.exe")

    script = session.create_script(JS)
    handle = out_path.open("w", encoding="utf-8")

    def on_message(message, _data):
        payload = message.get("payload") if message.get("type") == "send" else message
        handle.write(json.dumps(payload) + "\n")
        handle.flush()

    script.on("message", on_message)
    script.load()
    print(f"attached; logging to {out_path}")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(5)
    handle.close()
    strategy = safe_shutdown(session, script, kill=not args.keep_process, device=device)
    print(f"shutdown strategy: {strategy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
