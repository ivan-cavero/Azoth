#!/usr/bin/env python3
"""Dump the decoded LevelInfoChangedMsg struct (wire 0x663) and the player position.

WHY THIS EXISTS
===============
The 0x663 record is fully readable (zero redacted bytes) and its layout is measured,
but one question could not be settled from bytes alone: the four `u32` at record
`0x38/0x3c/0x40/0x44` hold `45 00 00 00`, `41 80 00 00`, `46 3f c0 00`, `46 20 28 00`.
Read as BIG-ENDIAN those are the floats 2048.0, 16.0, 12272.0, 10250.0; read as
little-endian they are 69, 32833, ... i.e. nothing.

Which one the client believes is not a matter of taste. The handler copies the field
verbatim (`*(u32*)(dst+0x50) = *(u32*)(src+0x50)`), so whatever sits in the decoded
struct is exactly what the client will interpret. If the struct holds `0x45000000`,
the client is looking at the float 2048.0 and a byte-swap happened during decode. If
it holds `0x00000045`, the field is not a float to the client at all and the
"big-endian float" reading is a coincidence.

So this probe reads the struct and reports the raw `u32` next to both float
interpretations. That is the measurement.

It also does three secondary things, all free once the session is open:

  * reads the two `std::string` fields, to confirm they really are the level name and
    level path (currently inferred from `FUN_146403a70`, not measured);
  * calls the client's OWN position accessor (`FUN_140fddfa0`, the same one behind the
    `nw_getPlayerPosition` console command) so the live world position can be compared
    against 12272.0 / 10250.0 -- the only second signal available for what those two
    numbers mean;
  * reports the `u8` flags at `+0xa0..+0xa3` and the dedup key at `+0xa8`.

The handler is virtual and hot, so the shutdown kills the client deliberately per
`_paths.safe_shutdown`: ending it removes the execute-after-unload race that a bare
`session.detach()` creates.

Usage:
    python -u reverse/probes/client/frida-levelinfo-struct.py --wait 420
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

HANDLER = 0x146447AC0  # FUN_146447ac0, the 0x663 handler on build 30fe6461
GETTER = 0x140FDDFA0   # FUN_140fddfa0, the client's own position accessor
POS_OFFSETS = (0x14C, 0x15C, 0x16C)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) { send({ err: 'NewWorld.exe not loaded' }); }
const base = mod.base;
const rva = (v) => base.add(v - 0x140000000);

const HANDLER = rva(0x146447ac0);
const GETTER  = new NativeFunction(rva(0x140fddfa0), 'pointer', ['pointer']);
const OFFSETS = %OFFSETS%;

// MSVC std::string: 16-byte inline buffer at +0, size at +0x10, capacity at +0x18.
// Capacity >= 16 means the characters live behind the pointer stored at +0.
function readStr(p) {
  try {
    const size = p.add(0x10).readU64().toNumber();
    const cap  = p.add(0x18).readU64().toNumber();
    if (size > 4096) return { size: size, cap: cap, text: '<implausible size>' };
    const data = (cap >= 16) ? p.readPointer() : p;
    return { size: size, cap: cap, text: data.readUtf8String(size) };
  } catch (e) { return { err: String(e) }; }
}

function f32le(u) { const b = Memory.alloc(4); b.writeU32(u); return b.readFloat(); }

function readStruct(s) {
  const u = (o) => s.add(o).readU32();
  const out = {};
  out.name = readStr(s);              // +0x00
  out.path = readStr(s.add(0x28));    // +0x28
  out.quads = [u(0x50), u(0x54), u(0x58), u(0x5c)].map(function (v) {
    // The handler copies these verbatim, so `v` is literally what the client holds.
    // 0x45000000 -> the client holds the float 2048.0 (a byte swap happened on decode).
    // 0x00000045 -> it does not, and the big-endian reading was a coincidence.
    return { raw: v, hex: '0x' + v.toString(16).padStart(8, '0'), as_f32: f32le(v) };
  });
  out.u64_60 = s.add(0x60).readU64().toString();
  out.u64_a8 = s.add(0xa8).readU64().toString();
  out.flags_a0_a3 = [0,1,2,3].map(function (i) { return s.add(0xa0 + i).readU8(); });
  return out;
}

function position() {
  try {
    const out = Memory.alloc(0x18);
    out.writeByteArray(new Uint8Array(0x18));
    GETTER(out);
    const holder = out.readPointer();
    if (holder.isNull()) return { ok: false, reason: 'null holder' };
    const vals = {};
    OFFSETS.forEach(function (off) { vals[off] = holder.add(off).readFloat(); });
    return { ok: true, vals: vals };
  } catch (e) { return { ok: false, reason: String(e) }; }
}

let hits = 0;
Interceptor.attach(HANDLER, {
  onEnter(args) {
    hits++;
    const rec = { hit: hits, struct: args[1].toString() };
    try { rec.fields = readStruct(args[1]); } catch (e) { rec.error = String(e); }
    rec.position = position();
    send(rec);
  }
});
send({ ready: true, handler: HANDLER.toString() });
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", type=int, default=420,
                    help="seconds to wait for the first hit (default 420)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = Path(args.out) if args.out else probe_capture("levelinfo-struct.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    def flush() -> None:
        """Write after every record: the shutdown kills the client, so an in-memory
        list would be lost if the capture outlived the wait."""
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
            f = payload.get("fields") or {}
            q = f.get("quads") or []
            print(f"[probe] hit {payload.get('hit')}: "
                  f"name={(f.get('name') or {}).get('text')!r} "
                  f"path={(f.get('path') or {}).get('text')!r} "
                  f"quads={[x.get('hex') for x in q]} "
                  f"as_f32={[round(x.get('as_f32') or 0, 3) for x in q]} "
                  f"pos={(payload.get('position') or {}).get('vals')}", flush=True)
        else:
            print(f"[probe:{msg.get('type')}] {msg.get('description') or msg}", flush=True)

    device = frida.get_local_device()
    session = device.attach("NewWorld.exe")
    script = session.create_script(JS.replace("%OFFSETS%", json.dumps(list(POS_OFFSETS))))
    script.on("message", on_msg)
    script.load()

    deadline = time.time() + args.wait
    try:
        # Exit as soon as a record lands (plus a short grace for repeats), so the
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

    safe_shutdown(session, script, kill=True, device=device)
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
