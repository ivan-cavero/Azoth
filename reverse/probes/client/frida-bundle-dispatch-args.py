#!/usr/bin/env python3
"""What does the inbound decode entry `0x146b6ea20` actually receive?

WHY THIS EXISTS
===============
To decide whether the client's wire-type-0x8 handler is CALLED for the 46,407-byte
spawn record, the handler has to be found first, and no xref can find it: the
decode entry reaches handlers through **virtual slot +0x20** of the stream
processor, so no plain `call` to a message handler exists in the image.

The parent supplied `0x146b6ea20` as a VERIFIED 1.460 anchor and `0x14029f9f0` as
the verified target of processor slot `+0x20`. This probe measures their argument
shapes on the running build, which is the missing piece needed to read a message's
type and length from inside a hook -- without that, a hook can count calls but
cannot say which call carried the bundle.

It also re-runs the pointer scan against the ASLR-relocated image (the first recon
pass searched for link-time VAs, which never occur in a relocated process, so it
returned zero hits by construction and not because the vtables are absent).

No interpretation is baked in: every argument is reported as a raw value plus the
first bytes it points at, so the signature is read off the client rather than
assumed.

Usage:
    python -u reverse/probes/client/frida-bundle-dispatch-args.py [--calls 40]
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

DECODE_ENTRY = 0x146B6EA20
PROCESSOR_SLOT_20 = 0x14029F9F0

POINTER_TARGETS = {
    "handler_0x65c": 0x146455EC0,
    "thunk_0x65c": 0x146455EAC,
    "handler_0x663": 0x146447AC0,
    "thunk_0x663": 0x146447AA8,
    "processor_slot_plus20": 0x14029F9F0,
    "inbound_decode_entry": 0x146B6EA20,
}

JS = r"""
const DECODE_ENTRY = __DECODE_ENTRY__;
const PROCESSOR_SLOT_20 = __PROCESSOR_SLOT_20__;
const POINTER_TARGETS = __POINTER_TARGETS__;
const MAX_CALLS = __MAX_CALLS__;

const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const at = (va) => base.add(rva(va));
const off = (p) => '0x' + p.sub(base).add(0x140000000).toString(16);

function hex(p, n) {
  try {
    const b = new Uint8Array(p.readByteArray(n));
    return Array.from(b).map((x) => x.toString(16).padStart(2, '0')).join(' ');
  } catch (e) { return null; }
}

function pattern(bytes) {
  return Array.from(bytes).map((x) => x.toString(16).padStart(2, '0')).join(' ');
}

// Runtime address of a link-time VA, as 8 little-endian bytes.
function le64OfVa(va) {
  const p = at(va);
  const n = parseInt(p.toString(), 16);
  const out = [];
  let v = n;
  for (let i = 0; i < 8; i++) { out.push(v % 256); v = Math.floor(v / 256); }
  return out;
}

// ---- pointer scan, now against the relocated image ----
const ranges = mod.enumerateRanges('r--');
const pointer_hits = {};
for (const name of Object.keys(POINTER_TARGETS)) {
  const pat = pattern(le64OfVa(POINTER_TARGETS[name]));
  const hits = [];
  for (const r of ranges) {
    if (r.size > 0x40000000) continue;
    let found = [];
    try { found = Memory.scanSync(r.base, r.size, pat); } catch (e) { continue; }
    for (const f of found) hits.push(off(f.address));
    if (hits.length > 64) break;
  }
  pointer_hits[name] = hits.slice(0, 64);
}
send({ ev: 'pointer_hits', hits: pointer_hits });

// ---- argument shapes at the two verified anchors ----
const calls = [];
let decodeCalls = 0;
let slotCalls = 0;

function describeArg(a) {
  const out = { raw: a.toString() };
  try {
    const p = ptr(a.toString());
    // Only dereference plausible user/kernel-shared pointers.
    if (p.compare(ptr('0x10000')) > 0) {
      out.head = hex(p, 32);
      out.u32_00 = p.readU32();
      out.u64_00 = p.readU64().toString();
    }
  } catch (e) { out.err = String(e).slice(0, 40); }
  return out;
}

function recordArgs(tag, args) {
  const row = { tag, args: [] };
  for (let i = 0; i < 8; i++) row.args.push(describeArg(args[i]));
  try {
    row.this_vtable = off(args[0].readPointer());
    row.this_vtable_slot20 = off(args[0].readPointer().add(0x20).readPointer());
    row.this_head = hex(args[0], 64);
  } catch (e) { row.this_err = String(e).slice(0, 40); }
  return row;
}

Interceptor.attach(at(DECODE_ENTRY), {
  onEnter(args) {
    decodeCalls++;
    if (calls.length < MAX_CALLS) {
      const row = recordArgs('decode_entry', args);
      row.n = decodeCalls;
      row.backtrace = Thread.backtrace(this.context, Backtracer.ACCURATE)
        .slice(0, 8).map(off);
      calls.push(row);
      send({ ev: 'call', row });
    }
  },
});

Interceptor.attach(at(PROCESSOR_SLOT_20), {
  onEnter(args) {
    slotCalls++;
    if (calls.length < MAX_CALLS) {
      const row = recordArgs('processor_slot_20', args);
      row.n = slotCalls;
      row.backtrace = Thread.backtrace(this.context, Backtracer.ACCURATE)
        .slice(0, 8).map(off);
      calls.push(row);
      send({ ev: 'call', row });
    }
  },
});

send({ ev: 'hooked', decode_entry: off(at(DECODE_ENTRY)),
       slot20: off(at(PROCESSOR_SLOT_20)) });

rpc.exports = {
  teardown() { Interceptor.detachAll(); },
  counters() { return { decodeCalls, slotCalls, recorded: calls.length }; },
};
"""


def build_js(max_calls: int) -> str:
    js = JS
    js = js.replace("__DECODE_ENTRY__", hex(DECODE_ENTRY))
    js = js.replace("__PROCESSOR_SLOT_20__", hex(PROCESSOR_SLOT_20))
    js = js.replace("__POINTER_TARGETS__", json.dumps(POINTER_TARGETS))
    js = js.replace("__MAX_CALLS__", str(max_calls))
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calls", type=int, default=40)
    ap.add_argument("--wait", type=int, default=180)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    require_build(PROBE_BUILD_SHA256, "bundle-dispatch-args")

    out = Path(args.out) if args.out else probe_capture("bundle-dispatch-args.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {"calls": [], "pointer_hits": None}

    def flush() -> None:
        out.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            ev = payload.get("ev")
            if ev == "pointer_hits":
                state["pointer_hits"] = payload["hits"]
                flush()
                print("[probe] pointer hits recorded", flush=True)
            elif ev == "hooked":
                print(f"[probe] hooked decode_entry={payload['decode_entry']} "
                      f"slot20={payload['slot20']}", flush=True)
            elif ev == "call":
                state["calls"].append(payload["row"])
                flush()
                row = payload["row"]
                print(f"[probe] {row['tag']} #{row['n']} "
                      f"a0={row['args'][0]['raw']} a1={row['args'][1]['raw']} "
                      f"a2={row['args'][2]['raw']} a3={row['args'][3]['raw']}",
                      flush=True)
        else:
            print(f"[probe:{msg.get('type')}] {msg.get('description') or msg}", flush=True)

    device = frida.get_local_device()
    session = device.attach("NewWorld.exe")
    script = session.create_script(build_js(args.calls))
    script.on("message", on_msg)
    script.load()

    deadline = time.time() + args.wait
    while time.time() < deadline and len(state["calls"]) < args.calls:
        time.sleep(0.5)

    counters = {}
    try:
        counters = script.exports_sync.counters()
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] counters unavailable: {exc}", flush=True)
    state["counters"] = counters
    flush()
    print(f"[probe] counters {counters} -> {out}", flush=True)

    strategy = safe_shutdown(session, script, kill=False, device=device)
    print(f"[probe] shutdown: {strategy}", flush=True)
    return 0 if state["calls"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
