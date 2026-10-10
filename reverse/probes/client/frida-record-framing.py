#!/usr/bin/env python3
"""Derive the real record/fragment framing from the client's own reads.

WHY. Two container models fit the capture byte-for-byte, so the capture cannot
discriminate between them:

  A) `[marker][u8 kind][varint record_id][u8 fragment_count][fragments...]`
  B) `[marker][u8 record_count][per record: varint record_id, u8 fragment_count, fragments...]`

Both consume all 79 captured type-0x08 bodies exactly, because in this capture
`record_count` is always 1 and `fragment_count` is always 1 — so the two layouts
produce identical bytes. "Consumes the body exactly" is therefore not evidence.

The distinguishing evidence is what the CLIENT does. `FUN_146af20d0` reads one
record and then loops calling `FUN_146af2340` once per fragment, so:

  * the cursor delta across one `FUN_146af20d0` call = bytes the client read for
    that record;
  * the number of `FUN_146af2340` calls nested inside it = that record's
    fragment count, as the client sees it;
  * the first bytes at the cursor = the record's own header, so a live read can
    be matched back to a captured bundle.

If the client reads MORE records per body than the capture's 1, model B is right
and our parser is swallowing every record after the first.

Read-only.

Usage: python az.py probe frida-record-framing [--timeout 300]
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

  let depth = 0;          // nested FUN_146af2340 calls inside the current record
  let recordSeq = 0;
  const events = [];

  // FUN_146af2340(reader_ptr_ptr, out_vector) -> one fragment
  Interceptor.attach(off(0x146af2340), {
    onEnter(args) { depth++; },
    onLeave(ret) { depth--; }
  });

  // FUN_146af20d0(reader_ptr_ptr, out_u16_record_id, out_vector) -> one record
  Interceptor.attach(off(0x146af20d0), {
    onEnter(args) {
      this.ctx = null;
      this.before = null;
      this.startHex = null;
      this.idOut = args[1];          // out u16 record id
      this.outer = (depth === 0);
      this.fragBefore = depth;
      try {
        this.ctx = args[0].readPointer();
        this.before = this.ctx.add(0x10).readPointer();
        // 24 bytes at the cursor: the record header as the client sees it.
        const b = new Uint8Array(this.before.readByteArray(24));
        this.startHex = Array.from(b).map(x => x.toString(16).padStart(2,'0')).join('');
      } catch (e) { this.err = String(e); }
    },
    onLeave(ret) {
      if (!this.outer) return;      // only log top-level records
      recordSeq++;
      if (recordSeq > 200) return;
      let consumed = null, recordId = null;
      try {
        consumed = this.ctx.add(0x10).readPointer().sub(this.before).toInt32();
      } catch (e) { consumed = 'err:' + e; }
      try {
        recordId = this.idOut.readU16();
      } catch (e) { recordId = null; }
      send({ev:'record', n: recordSeq, consumed: consumed,
            fragments: depth - this.fragBefore, recordId: recordId, start: this.startHex});
    }
  });

  setInterval(function(){ send({ev:'alive', records: recordSeq}); }, 5000);
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--out", default="record-framing.jsonl")
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
