#!/usr/bin/env python3
"""Derive a record's fragment boundaries from the client, WITHOUT hooking the varint reader.

WHY THIS EXISTS. `frida-fragment-grammar.py` answers the same question but hooks the shared
prefix-varint reader (`FUN_14087b5c0`), which runs for EVERY varint read in the process —
thousands of times a second during world load. The runbook warns that hooking a hot function
"stalls the client thread", and the one attempt to use it at character select ended with the
client process gone during the Play click (no Application-Error event, no `InGame`). So this
probe hooks ONLY the two per-record readers and reads the fragment bytes directly:

    0x146af20d0  FUN_146af20d0(reader_ptr_ptr, out_u16, out_vector) -- one record
    0x146af2340  FUN_146af2340(reader_ptr_ptr, out_vector)          -- one fragment

The reader's cursor is at `ctx + 0x10`, so a fragment's byte span is `end - start` and the
first two prefix varints inside that span are its KEY and TYPE_INDEX. Parsing them here in JS
costs two Interceptor hooks instead of three, and neither is on a hot path.

SELF-VALIDATION, and this is the point. The probe reports, per record, the fragment spans AND
the record's own byte length, so the caller can check that the spans TILE the record exactly.
A boundary model that does not tile the record is wrong; that check is what "consumes the body
exactly" could never do, because an opaque-remainder model always consumes exactly.

Read-only. Ends through `_paths.safe_shutdown()`. NOTE the default: `safe_shutdown(..., kill=...)`
KILLS the client, which is right for a measurement run (every world A/B wants a fresh process)
and wrong for a soak. Pass `--keep-process` to leave it running.

Usage:
  python az.py probe frida-record-boundaries [--timeout 240] [--record 1] [--keep-process]
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);

  // Read the cursor the readers advance.
  const cursor = (readerPtrPtr) => readerPtrPtr.readPointer().add(0x10).readPointer();

  // The same prefix-varint shape the project's Python `varint.py` implements:
  // the leading 1-bits of the first byte give the continuation count, and the
  // continuation bytes are little-endian.
  function readVarint(ptr) {
    const first = ptr.readU8();
    let n = 0, mask = 0x80;
    while (first & mask) { n++; mask >>= 1; }
    if (n === 0) return { value: first, size: 1 };
    if (n > 4) return { value: null, size: 0, error: 'too many continuation bytes' };
    const shift = 7 - n;
    let cont = 0;
    for (let i = 0; i < n; i++) cont += ptr.add(1 + i).readU8() * Math.pow(2, 8 * i);
    return { value: (cont * Math.pow(2, shift)) + (first & ((1 << shift) - 1)), size: 1 + n };
  }

  let recordStart = null;
  let recordId = null;
  let fragStart = null;
  let depth = 0;
  let spans = [];
  let emitted = 0;
  let truncated = 0;
  const recordFilter = %RECORD%;

  Interceptor.attach(rva(0x146af20d0), {
    onEnter(args) {
      try {
        this.readerPtrPtr = args[0];
        recordStart = cursor(args[0]);
        spans = [];
        depth = 0;
        this.outId = args[1];
      } catch (e) { recordStart = null; }
    },
    onLeave(ret) {
      try { recordId = this.outId.readU16(); } catch (e) { recordId = null; }
      if (recordStart === null) return;
      let recordLength = null;
      try { recordLength = cursor(this.readerPtrPtr).sub(recordStart).toInt32(); } catch (e) {}
      const total = spans.reduce((a, s) => a + s.length, 0);
      if (recordFilter >= 0 && recordId !== recordFilter) return;
      if (emitted >= 60) { truncated++; return; }
      emitted++;
      // `tiles` is the self-check: the fragment spans must account for the whole
      // record, or the boundary model is wrong. An opaque-remainder model always
      // "consumes exactly", so this is the check that can actually fail.
      // The first fragment starts after the record header, so the spans tile the record
      // when `span_total + first_offset == record_length`.
      const firstOff = spans.length ? spans[0].off : null;
      send({ ev: 'record', n: emitted, recordId: recordId, fragments: spans.length,
             span_total: total, record_length: recordLength, first_offset: firstOff,
             tiles: recordLength === null || firstOff === null
               ? null : (total + firstOff === recordLength),
             boundaries: spans.map((s) => s.off),
             keys: spans.map((s) => s.key), types: spans.map((s) => s.type),
             header_sizes: spans.map((s) => s.header_size) });
    }
  });

  Interceptor.attach(rva(0x146af2340), {
    onEnter(args) {
      depth++;
      if (depth !== 1) return;
      try {
        this.readerPtrPtr = args[0];
        fragStart = cursor(args[0]);
      } catch (e) { fragStart = null; }
    },
    onLeave(ret) {
      depth--;
      if (depth !== 0 || fragStart === null) return;
      try {
        const end = cursor(this.readerPtrPtr);
        const length = end.sub(fragStart).toInt32();
        const header = readVarint(fragStart);
        const type = header.size ? readVarint(fragStart.add(header.size)) : { value: null, size: 0 };
        spans.push({ off: fragStart.sub(recordStart).toInt32(), length: length,
                     key: header.value, type: type.value,
                     header_size: header.size + type.size });
      } catch (e) {
        send({ ev: 'error', where: 'fragment', error: String(e) });
      }
    }
  });

  rpc.exports = {
    state() { return { records: emitted, truncated: truncated }; },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--record", type=int, default=-1,
                    help="only report this record id (-1 = all, capped at 60 records)")
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--keep-process", action="store_true",
                    help="leave the client running on exit; the default KILL is right for a "
                         "measurement and wrong for a soak")
    args = ap.parse_args()

    out_path = probe_capture(f"record-boundaries-{int(time.time())}.jsonl")
    device = frida.get_local_device()
    session = None
    for _ in range(90):
        try:
            session = device.attach(args.process)
            break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    if session is None:
        raise SystemExit(f"could not attach to {args.process}")

    script = session.create_script(JS.replace("%RECORD%", str(args.record)))
    handle = out_path.open("w", encoding="utf-8")

    def on_message(message, _data):
        payload = message.get("payload") if message.get("type") == "send" else message
        handle.write(json.dumps(payload) + "\n")
        handle.flush()

    script.on("message", on_message)
    script.load()
    print(f"attached; logging to {out_path}", flush=True)

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(5)
    try:
        print(f"state: {script.exports_sync.state()}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"state error: {exc}", flush=True)
    handle.close()
    strategy = safe_shutdown(session, script, kill=not args.keep_process, device=device)
    print(f"shutdown strategy: {strategy}", flush=True)
    print(f"done; capture {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
