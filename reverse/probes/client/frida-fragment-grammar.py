#!/usr/bin/env python3
"""Derive the per-fragment grammar from the client's own reads.

WHY. The record layer is settled (a `0x08` payload is a sequence of
`[u8 record_id][u8 fragment_count][fragments…]`), and the fragment SIZES are known
from the cursor deltas. What is not known is the fragment HEADER: how the client
knows where one fragment ends and the next begins.

Rather than guess from byte patterns, this probe records, for each fragment, the
sequence of prefix-varint reads the client performs inside it, with each read's
offset from the start of the enclosing record. That reconstructs the grammar
directly: if a fragment is `[varint key][varint type][payload]`, exactly two
varints appear at the fragment's start and their values are the key and type.

Hooks:
  0x14087b5c0  the shared prefix-varint reader
  0x146af20d0  the record reader (defines the record start offset)
  0x146af2340  the fragment reader (delimits one fragment)

Read-only.

Usage: python az.py probe frida-fragment-grammar [--timeout 240]
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);

  let recordStart = null;
  let fragStart = null;
  let fragVarints = [];
  let fragDepth = 0;
  let emitted = 0;

  // FUN_146af20d0(reader_ptr_ptr, out_u16, out_vector) -- one record
  Interceptor.attach(off(0x146af20d0), {
    onEnter(args) {
      try {
        const ctx = args[0].readPointer();
        recordStart = ctx.add(0x10).readPointer();
        fragDepth = 0;
        if (emitted < 40) send({ev:'record-start'});
      } catch (e) {}
    }
  });

  // FUN_146af2340(reader_ptr_ptr, out_vector) -- one fragment
  Interceptor.attach(off(0x146af2340), {
    onEnter(args) {
      fragDepth++;
      if (fragDepth !== 1) return;
      try {
        const ctx = args[0].readPointer();
        fragStart = ctx.add(0x10).readPointer();
        fragVarints = [];
      } catch (e) {}
    },
    onLeave(ret) {
      fragDepth--;
      if (fragDepth !== 0) return;
      emitted++;
      if (emitted > 300) return;
      let offInRecord = null;
      try { offInRecord = fragStart.sub(recordStart).toInt32(); } catch (e) {}
      send({ev:'fragment', n: emitted, offInRecord: offInRecord,
            varints: fragVarints});
    }
  });

  // FUN_14087b5c0(out_ok, out_ok2, out_value_u32, reader) -- one prefix varint
  Interceptor.attach(off(0x14087b5c0), {
    onEnter(args) {
      this.reader = args[3];
      this.valueOut = args[2];
      try { this.before = this.reader.add(0x10).readPointer(); } catch (e) { this.before = null; }
    },
    onLeave(ret) {
      if (fragStart === null || !this.before) return;
      let value = null, size = null, offInFrag = null;
      try { value = this.valueOut.readU32(); } catch (e) {}
      try {
        const after = this.reader.add(0x10).readPointer();
        size = after.sub(this.before).toInt32();
        offInFrag = this.before.sub(fragStart).toInt32();
      } catch (e) {}
      if (fragVarints.length < 8) {
        fragVarints.push({off: offInFrag, value: value, size: size});
      }
    }
  });
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--out", default="fragment-grammar.jsonl")
    args = parser.parse_args()
    out_path = probe_capture(args.out)
    device = frida.get_local_device()
    session = None
    for _ in range(90):
        try:
            session = device.attach("NewWorld.exe")
            break
        except Exception:
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
    try:
        session.detach()
    except Exception:
        pass
    handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
