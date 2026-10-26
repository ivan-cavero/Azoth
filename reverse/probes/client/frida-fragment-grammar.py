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

The record reader's SECOND argument is its `out_u16`, so the record id is available: every
fragment event carries the record id it belongs to, which is what makes it possible to pick out
record 1 (the local-player metadata slot) from the flood.

Read-only. Ends through `_paths.safe_shutdown()`: a bare `session.detach()` was measured to kill
this client minutes later with an execute-after-unload fault, and that has been mistaken for a
client bug twice.

Usage: python ef.py probe frida-fragment-grammar [--timeout 240] [--record 1]
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, require_build, safe_shutdown

# EMPTY ON PURPOSE -- THIS PROBE IS STALE AND MUST NOT RUN AS IS.
#
# Its three VAs were derived on 1.400 and are not valid on 1.460: the byte at
# 0x14087b5c0 in the current build is the start of movhps/movaps/mulps float
# arithmetic, not the varint branch ladder these hooks assume. No hash of the 1.400
# runtime copy was ever recorded, so this probe cannot state a build it can verify
# against, and require_build() refuses to attach without one. A hook on a stale
# address succeeds silently and measures unrelated code -- that is the failure this
# guard exists to prevent, so the honest state is "refuse" rather than a guess.
#
# To use it again: re-derive the three VAs against the target build, then set this
# to that build's runtime SHA-256 (private-client/runtime/Bin64/NewWorld.exe).
PROBE_BUILD_SHA256 = ""

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);

  // MEASURED 2026-10-18: this probe used to read the record's out_u16 in the record
  // reader's onLeave and attach it to each fragment event. That CANNOT work: fragments are
  // emitted in the fragment reader's onLeave, which runs BEFORE the record's onLeave, so
  // every one of the 300 captured fragment events carried recordId null. The record id is
  // therefore read at RECORD LEAVE and the fragments are buffered and emitted there, which
  // is the only point where both the id and the fragment list exist.
  //
  // The record id ALONE does not identify a record: the spawn record and the local-player
  // metadata record are BOTH record_id 1 (46393 vs 7154 bytes of payload). A consumer must
  // distinguish them by fragment count / payload size, which is why both are emitted.

  let recordStart = null;
  let recordFragments = [];
  let fragStart = null;
  let fragVarints = [];
  let fragDepth = 0;
  let recordsEmitted = 0;

  // FUN_146af20d0(reader_ptr_ptr, out_u16, out_vector) -- one record
  Interceptor.attach(off(0x146af20d0), {
    onEnter(args) {
      try {
        const ctx = args[0].readPointer();
        recordStart = ctx.add(0x10).readPointer();
        fragDepth = 0;
        recordFragments = [];
        this.outId = args[1];
      } catch (e) {}
    },
    onLeave(ret) {
      let recordId = null;
      try { recordId = this.outId.readU16(); } catch (e) {}
      let payloadBytes = null;
      try {
        const ctx = this.context;
      } catch (e) {}
      recordsEmitted++;
      send({ev:'record', n: recordsEmitted, recordId: recordId,
            fragmentCount: recordFragments.length,
            fragments: recordFragments});
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
      let offInRecord = null;
      try { offInRecord = fragStart.sub(recordStart).toInt32(); } catch (e) {}
      recordFragments.push({offInRecord: offInRecord, varints: fragVarints});
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
      if (fragVarints.length < 12) {
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
    parser.add_argument("--min-fragments", type=int, default=0,
                        help="only record events for records with at least this many fragments "
                             "(the spawn record has 48; the local-player metadata record has 9)")
    parser.add_argument("--keep-process", action="store_true",
                        help="leave the client running on exit (orderly detach) instead of "
                             "ending it; the default kill is safer")
    args = parser.parse_args()
    require_build(PROBE_BUILD_SHA256, "frida-fragment-grammar")
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
        # The record id does NOT identify a record: the spawn record and the local-player
        # metadata record are BOTH record_id 1 (46393 vs 7154 payload bytes). Filtering by
        # fragment count is what separates them, and it also keeps this capture small.
        if (
            args.min_fragments
            and isinstance(payload, dict)
            and payload.get("ev") == "record"
            and (payload.get("fragmentCount") or 0) < args.min_fragments
        ):
            return
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
