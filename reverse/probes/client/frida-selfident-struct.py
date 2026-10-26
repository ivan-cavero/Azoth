#!/usr/bin/env python3
"""Dump the decoded PlayerManagerSelfIdentificationMsg struct (wire 0x65c).

WHY THIS EXISTS
===============
`research/atlas/meanings.md` carries the 0x65c body as 12,706 bytes, 32 of which
the official replay redacts. Static analysis of the handler proved the STRUCT
(`0x00` u32, `0x08` std::vector, `0x28` u8, `0x2c` u64, `0x34` u32 = `0x38`) but
cannot place one orphan byte in the wire order, because arithmetic over fabricated
zeros proves nothing.

The client, however, decodes the record for real. `FUN_146455ec0` receives the
already-decoded struct in its `param_6`. Reading that struct back gives the vector's
element COUNT and the first elements, which is exactly the number the wire
arithmetic could not produce: count x element width must account for the payload.

So this probe answers one question with a measurement instead of a guess: how many
elements does the vector hold, and how wide are they?

WHAT IT DOES
============
Hooks the handler and, on each hit, records:
  struct+0x00  u32
  struct+0x08  the std::vector triple {begin, end, capacity} plus
               count = (end-begin)/elem, first N elements, and the span in bytes
  struct+0x28  u8   (the debug-cvar spawn switch the handler branches on)
  struct+0x2c  u64
  struct+0x34  u32

The element width is not assumed: the probe reports the byte span and a few
candidate widths so the reader can see which one divides evenly.

The handler is a HOT-ish virtual, so the shutdown uses `kill=True` per
`_paths.safe_shutdown`: ending the process deliberately removes the
execute-after-unload race that a bare `session.detach()` creates.

Usage:
    python reverse/probes/client/frida-selfident-struct.py [--wait 900]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import probe_capture, safe_shutdown  # noqa: E402

import frida  # noqa: E402

HANDLER = 0x146455EC0  # FUN_146455ec0, the 0x65c handler on build 30fe6461

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({err: 'NewWorld.exe not loaded'}); }
const base = mod.base;
const rva = (v) => v - 0x140000000;

const HANDLER = base.add(rva(0x146455ec0));
const MAX_ELEMS = 24;

function u32(p) { try { return p.readU32(); } catch (e) { return null; } }
function u64(p) { try { return p.readU64().toString(); } catch (e) { return null; } }
function u8(p)  { try { return p.readU8();  } catch (e) { return null; } }

let hits = 0;
Interceptor.attach(HANDLER, {
  onEnter(args) {
    hits++;
    // param_6 is the 7th argument -> args[5]
    const s = args[5];
    const rec = { hit: hits, struct_ptr: s.toString() };
    try {
      rec.u32_at_00 = u32(s);
      rec.u8_at_28   = u8(s.add(0x28));
      rec.u64_at_2c  = u64(s.add(0x2c));
      rec.u32_at_34  = u32(s.add(0x34));

      const begin = s.add(0x08).readPointer();
      const end   = s.add(0x10).readPointer();
      const cap   = s.add(0x18).readPointer();
      rec.vec_begin = begin.toString();
      rec.vec_end   = end.toString();
      rec.vec_cap   = cap.toString();

      const span = end.sub(begin).toInt32();
      rec.vec_span_bytes = span;
      // Do not assume the element width: report which widths divide the span.
      rec.span_divisible_by = {};
      [1,2,4,8,16].forEach(w => { rec.span_divisible_by[w] = (span % w === 0); });

      const elems = [];
      const n = Math.min(MAX_ELEMS, Math.floor(span / 4));
      for (let i = 0; i < n; i++) {
        try { elems.push(begin.add(i*4).readU32()); } catch (e) { break; }
      }
      rec.first_u32 = elems;
    } catch (e) {
      rec.error = String(e);
    }
    send(rec);
  }
});
send({ready: true, handler: HANDLER.toString()});
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", type=int, default=900,
                    help="seconds to wait for the first hit (default 900)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = Path(args.out) if args.out else probe_capture("selfident-struct.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    def flush() -> None:
        """Write after every record: the shutdown kills the client, so an
        in-memory list would be lost if the capture outlived the wait."""
        out.write_text(json.dumps({"handler": hex(HANDLER), "records": records},
                                  indent=2) + "\n", encoding="utf-8")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            if payload.get("ready"):
                print(f"[probe] attached, handler {payload.get('handler')}", flush=True)
                return
            records.append(payload)
            flush()
            print(f"[probe] hit {payload.get('hit')}: "
                  f"u32@0x00={payload.get('u32_at_00')} "
                  f"u8@0x28={payload.get('u8_at_28')} "
                  f"vec_span={payload.get('vec_span_bytes')} "
                  f"first={payload.get('first_u32')}", flush=True)
        else:
            print(f"[probe:{msg.get('type')}] {msg.get('description') or msg}", flush=True)

    device = frida.get_local_device()
    session = device.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", on_msg)
    script.load()

    deadline = time.time() + args.wait
    try:
        # Exit as soon as the record lands (plus a short grace for repeats), so the
        # deliberate kill does not have to wait out the whole window.
        while time.time() < deadline:
            if records:
                time.sleep(2)
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    flush()
    print(f"[probe] {len(records)} record(s) -> {out}", flush=True)

    # kill=True: deliberate, so no agent-unload race can be mistaken for client behaviour.
    safe_shutdown(session, script, kill=True, device=device)
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
