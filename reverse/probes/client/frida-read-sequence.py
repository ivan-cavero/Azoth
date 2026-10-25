#!/usr/bin/env python3
"""Reconstruct the client's exact read sequence over a state-bundle body.

WHY. `frida-record-framing` showed that when `FUN_146af20d0` is entered the decode
cursor already sits at the fragment PAYLOAD, and it consumes exactly the length
field's worth of bytes (46393 for the spawn record, recordId 1) with NO nested
`FUN_146af2340` call. So the header is consumed BEFORE that entry, and the
call-graph reading of which function reads which field is not reliable enough to
build on.

This probe stops guessing: it logs, in order, every varint read the client makes
and every cursor position, plus the raw bytes at each cursor, so the read
sequence over one body can be reconstructed from the client's own behaviour.

Hooks:
  0x14087b5c0  the shared prefix-varint reader (logs value + cursor before/after)
  0x146af20d0  the outer record reader
  0x146af2340  the inner reader

Read-only.

Usage: python ef.py probe frida-read-sequence [--timeout 240]
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
  let varints = 0, outer = 0, inner = 0;
  const hex = (p, n) => {
    try { return Array.from(new Uint8Array(p.readByteArray(n)))
      .map(x => x.toString(16).padStart(2,'0')).join(''); } catch (e) { return 'err'; }
  };

  // FUN_14087b5c0(out_ok, out_ok2, out_value_u32, reader) -- prefix varint
  Interceptor.attach(off(0x14087b5c0), {
    onEnter(args) {
      this.reader = args[3];
      this.valueOut = args[2];
      try { this.before = this.reader.add(0x10).readPointer(); } catch (e) {}
      this.start = this.before ? hex(this.before, 12) : null;
    },
    onLeave(ret) {
      varints++;
      if (varints > 400) return;
      let value = null, delta = null;
      try { value = this.valueOut.readU32(); } catch (e) {}
      try { delta = this.reader.add(0x10).readPointer().sub(this.before).toInt32(); } catch (e) {}
      send({ev:'varint', n: varints, value: value, bytes: delta, at: this.start});
    }
  });

  // Only log the FIRST occurrence of each distinct outer start, so a bundle the
  // server re-sends does not crowd out the other bundles.
  const seenOuter = {};
  let outerLogged = 0;
  let counting = false;      // true only while inside an outer record call
  let innerInOuter = 0;      // inner calls made by the current outer record
  Interceptor.attach(off(0x146af20d0), {
    onEnter(args) {
      outer++;
      this.reader = null;
      counting = true;
      innerInOuter = 0;
      try { this.reader = args[0].readPointer(); this.before = this.reader.add(0x10).readPointer(); } catch (e) {}
      this.start = this.before ? hex(this.before, 40) : null;
    },
    onLeave(ret) {
      let delta = null;
      try { delta = this.reader.add(0x10).readPointer().sub(this.before).toInt32(); } catch (e) {}
      const key = String(delta) + ':' + String(this.start).slice(0, 24);
      if (seenOuter[key]) return;
      seenOuter[key] = true;
      outerLogged++;
      if (outerLogged > 90) return;
      const frags = innerInOuter;
      counting = false;
      send({ev:'outer', n: outer, distinct: outerLogged, consumed: delta,
            frags: frags, at: this.start});
    }
  });

  const seenInner = {};
  let innerLogged = 0;
  Interceptor.attach(off(0x146af2340), {
    onEnter(args) {
      inner++;
      if (counting) innerInOuter++;
      this.reader = null;
      try { this.reader = args[0].readPointer(); this.before = this.reader.add(0x10).readPointer(); } catch (e) {}
      this.start = this.before ? hex(this.before, 40) : null;
    },
    onLeave(ret) {
      let delta = null;
      try { delta = this.reader.add(0x10).readPointer().sub(this.before).toInt32(); } catch (e) {}
      const key = String(delta) + ':' + String(this.start).slice(0, 40);
      if (seenInner[key]) return;
      seenInner[key] = true;
      innerLogged++;
      if (innerLogged > 200) return;
      send({ev:'inner', n: inner, distinct: innerLogged, consumed: delta, at: this.start});
    }
  });

  setInterval(function(){ send({ev:'alive', varints: varints, outer: outer, inner: inner}); }, 5000);
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--out", default="read-sequence.jsonl")
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
