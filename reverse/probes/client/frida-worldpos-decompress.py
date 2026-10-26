#!/usr/bin/env python3
"""Dump the worldPosAbs member when the client decompresses it (build 1.460).

WHY THIS EXISTS
===============
`research/atlas/meanings.md` records the delta format for `ALCReplicatedState` and
names its field table, so `worldPosAbs` (group 0, bit 26) is known BY NAME. What is
NOT known is the wire encoding of its absolute quad: the decompressor reads four
host-order floats from `member+0x10..0x1c`, while the spawn payload carries an f32
BIG-ENDIAN pair at payload +20. How the wire bytes become those floats has not been
measured, and it is the one thing still blocking a Rust position encoder that
composes state field by field rather than echoing captured bytes.

Static reading cannot settle it. The field codecs are per-field-type and reached
through the field object's own vtable (`+0x30` read, `+0x28` write, `+0x18`
present), and the field objects are built by the ALC constructor from a prototype,
so the chain runs through several indirections that the decompiler renders as
pointer arithmetic. Guessing at that arithmetic is how a wrong schema gets written
down.

The client, however, decompresses the field for real. FUN_142a28350 is that
decompressor: ALC vtable `+0x78` is a two-line trampoline into it, and it is called
with `param_1 = ALC + 0x8c0`, the `worldPosAbs` member itself. Reading the member
back at the moment the client uses it answers the question directly.

WHAT IT DOES
============
Hooks `FUN_142a28350` and, per hit, records:

  member +0x00..+0x90   raw bytes, plus a u32 and f32 reading of every 8-byte row,
                        so the absolute quad, the three quantized bytes and the
                        scale are all visible in one shot
  member +0x10..+0x1c   the four "absolute" floats the decompressor consumes
  member +0x60/+0x61/+0x62  the quantized deltas
  member +0x88          the quantization scale
  output (onLeave)      the four floats the decompressor produced

The decisive comparison is the FIRST of those floats against the wire value the
atlas already has: 9343.6416015625 and 2786.732666015625 as f32 big-endian at spawn
payload offsets 38332/38336. If `member+0x10` already holds those numbers, the wire
bytes land as host floats and a Rust encoder writes f32 big-endian. If it holds
something else, the quad is a different representation and the difference says what.

Read-only: nothing is written to the client. Shutdown keeps the process by default,
because an in-world client is expensive to reach and this probe is meant to be run
against one that already reached the world.

Usage:
    python -u reverse/probes/client/frida-worldpos-decompress.py [--wait 240]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import probe_capture, require_build, safe_shutdown  # noqa: E402

import frida  # noqa: E402

PROBE_BUILD_SHA256 = "97f17df315aef97bed1303bb9d57330be67e9e0c9e22acb59dde68de837b743c"

DECOMPRESS = 0x142A28350  # FUN_142a28350, called with param_1 = ALC + 0x8c0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) {
  send({err: 'NewWorld.exe not loaded'});
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);

  const f32 = (u) => {
    const buf = Memory.alloc(4);
    buf.writeU32(u >>> 0);
    return buf.readFloat();
  };

  let hits = 0;
  const MAX_HITS = 6;

  Interceptor.attach(rva(0x142A28350), {
    onEnter(args) {
      this.member = args[0];
      this.out = args[1];
      this.rec = null;
      if (hits >= MAX_HITS) return;
      try {
        // The member is 0x90 bytes of interest; read it whole so the absolute
        // quad, the quantized bytes and the scale are all in one record.
        const n = 0x90;
        const raw = this.member.readByteArray(n);
        const bytes = [];
        const u8 = new Uint8Array(raw);
        for (let i = 0; i < u8.length; i++) bytes.push(u8[i]);

        const rows = [];
        for (let off = 0; off < n; off += 8) {
          const u0 = this.member.add(off).readU32();
          const u1 = this.member.add(off + 4).readU32();
          rows.push({ off, u0, f0: f32(u0), u1, f1: f32(u1) });
        }

        this.rec = {
          ev: 'hit',
          n: ++hits,
          member: this.member.toString(),
          out: this.out.toString(),
          absolute_quad: {
            x: f32(this.member.add(0x10).readU32()),
            y: f32(this.member.add(0x14).readU32()),
            z: f32(this.member.add(0x18).readU32()),
            w: f32(this.member.add(0x1c).readU32()),
          },
          quantized_bytes: {
            b0: this.member.add(0x60).readU8(),
            b1: this.member.add(0x61).readU8(),
            b2: this.member.add(0x62).readU8(),
          },
          scale_u32: this.member.add(0x88).readU32(),
          scale_f32: f32(this.member.add(0x88).readU32()),
          bytes,
          rows,
        };
      } catch (e) {
        send({ev: 'error', msg: String(e) });
      }
    },
    onLeave(retval) {
      if (!this.rec) return;
      try {
        this.rec.result = {
          x: f32(this.out.readU32()),
          y: f32(this.out.add(4).readU32()),
          z: f32(this.out.add(8).readU32()),
          w: f32(this.out.add(12).readU32()),
        };
      } catch (e) {
        this.rec.result_error = String(e);
      }
      send(this.rec);
    },
  });

  send({ ev: 'ready', decompress: '0x142a28350' });
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", type=float, default=240.0,
                        help="seconds to watch before giving up")
    parser.add_argument("--out", default="worldpos-decompress.jsonl")
    parser.add_argument("--kill-process", action="store_true",
                        help="end the client on exit; default keeps it, because an "
                             "in-world client is expensive to reach")
    args = parser.parse_args()

    require_build(PROBE_BUILD_SHA256, "frida-worldpos-decompress")
    out_path = probe_capture(args.out)
    device = frida.get_local_device()

    session = None
    for _ in range(30):
        try:
            session = device.attach("NewWorld.exe")
            break
        except Exception:
            time.sleep(2)
    if session is None:
        raise SystemExit("could not attach to NewWorld.exe")

    script = session.create_script(JS)
    handle = out_path.open("w", encoding="utf-8")
    hits = {"n": 0}

    def on_message(message, _data):
        payload = message.get("payload") if message.get("type") == "send" else message
        handle.write(json.dumps(payload) + "\n")
        handle.flush()
        if isinstance(payload, dict):
            if payload.get("ev") == "ready":
                print(f"attached; watching FUN_142a28350 -> {out_path}")
            elif payload.get("ev") == "hit":
                hits["n"] += 1
                q = payload.get("absolute_quad") or {}
                print(f"  hit {payload['n']}: abs=({q.get('x')}, {q.get('y')}, "
                      f"{q.get('z')}, {q.get('w')})")
            elif payload.get("ev") == "error":
                print(f"  probe error: {payload.get('msg')}")

    script.on("message", on_message)
    script.load()

    deadline = time.time() + args.wait
    while time.time() < deadline and hits["n"] < 3:
        time.sleep(2)
    handle.close()
    strategy = safe_shutdown(session, script, kill=args.kill_process, device=device)
    print(f"shutdown strategy: {strategy}")
    if hits["n"] == 0:
        print("NO HITS. That is a fact worth recording, not a failure: the decompressor "
              "may only run on a position delta, or the client may not have taken one.")
    else:
        print(f"{hits['n']} hit(s) recorded in {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
