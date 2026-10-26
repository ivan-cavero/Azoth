#!/usr/bin/env python3
"""Reconnaissance for the wire-type-0x8 `ReplicatedStateBundle` handler on 1.460.

WHY THIS EXISTS
===============
`research/atlas/meanings.md` ("Rung 17: the client accepts the record and waits")
records that the 46,407-byte spawn record decodes with zero `Failed to unmarshal`
and zero `ValidationError`, and that the state machine still expires. What is
unmeasured is whether the client's 0x8 handler is ever CALLED for that record.

Finding that handler is the hard half, and it cannot be done with an xref: the
inbound decode entry `0x146b6ea20` reaches handlers through **virtual slot +0x20**
of the stream processor (vtable `0x148590ab8`, slot `+0x20` = `0x14029f9f0`), so
nothing in the image contains a plain call to a message handler. That is also why
the parent's lead is worth executing live: the two verified 1.460 handlers
(`0x146455ec0` for `0x65c`, `0x146447ac0` for `0x663`) sit in adjacent slots of
one vtable, so their neighbours are the cheapest place to look for a third.

This probe hooks NOTHING. It only reads the live image, so it is safe to run and
safe to detach from, and it answers, on the running build:

  1. Do the parent's 1.460 anchors still hold? (entry bytes at each anchor)
  2. Which vtables contain the two VERIFIED 1.460 handlers, and what are the
     neighbouring slots and their entry bytes?
  3. What are the 35 slots of the processor vtable `0x148590ab8`, and is slot
     `+0x20` really `0x14029f9f0`?
  4. Where in the live image do the log format strings the rung-17 evidence
     quotes live (`ReceiveStateBundle`, `HandleUnexpectedMessage`, `player spawn
     succeeds`, `Failed to unmarshal`, `ValidationError`, ...)? A pointer to one
     of those strings is a direct handle on the code that logs it, which is the
     bundle receive/apply path -- a second, independent route to the handler that
     does not depend on any vtable guess.
  5. Which vtables share slot `+0x20` = `0x14029f9f0` (i.e. is it a generic
     dispatch entry or a per-type handler)?

Reading the loaded image at run time is dynamic measurement of the process the
launcher started. Nothing here is a static/decompiler pass, and the private copy
is never opened as a file.

Usage:
    python -u reverse/probes/client/frida-bundle-handler-recon.py [--out FILE]
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

# private-client/runtime/Bin64/NewWorld.exe -- the copy the launcher runs.
PROBE_BUILD_SHA256 = "97f17df315aef97bed1303bb9d57330be67e9e0c9e22acb59dde68de837b743c"

# Verified 1.460 anchors, supplied by the parent and re-checked here by entry bytes.
ANCHORS = {
    "handler_0x65c": 0x146455EC0,
    "thunk_0x65c": 0x146455EAC,
    "handler_0x663": 0x146447AC0,
    "thunk_0x663": 0x146447AA8,
    "inbound_decode_entry": 0x146B6EA20,
    "processor_slot_plus20": 0x14029F9F0,
    "player_mgr_vtable": 0x1484FDB78,
    "processor_vtable": 0x148590AB8,
}

# Log lines the rung-17 evidence quotes. Finding the format string gives a
# second, vtable-independent route to the code that emits it.
LOG_STRINGS = [
    "ReceiveStateBundle",
    "HandleUnexpectedMessage",
    "skipping ReceiveStateBundle",
    "clientContext == nullptr",
    "ProcessPendingReliableMsgQueue",
    "player spawn succeeds",
    "Received new local player metadata",
    "Failed to unmarshal",
    "ValidationError",
    "Calling clientContext->Initialize",
    "m_pendingUnexpectedMsgs",
]

# Pointers worth locating in the image: each hit is a vtable slot (or a
# function-pointer field) that names the code by address.
POINTER_TARGETS = {
    "handler_0x65c": 0x146455EC0,
    "thunk_0x65c": 0x146455EAC,
    "handler_0x663": 0x146447AC0,
    "thunk_0x663": 0x146447AA8,
    "processor_slot_plus20": 0x14029F9F0,
    "inbound_decode_entry": 0x146B6EA20,
}

JS = r"""
const ANCHORS = __ANCHORS__;
const LOG_STRINGS = __LOG_STRINGS__;
const POINTER_TARGETS = __POINTER_TARGETS__;

const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({err: 'NewWorld.exe not loaded'}); }
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

function le64(v) {
  const out = [];
  let n = v;
  for (let i = 0; i < 8; i++) { out.push(n % 256); n = Math.floor(n / 256); }
  return out;
}

const out = {
  base: base.toString(),
  anchors: {},
  vtables: {},
  log_strings: {},
  pointer_hits: {},
  slot20_sharers: [],
};

// ---- 1. anchors: entry bytes, so a stale VA cannot pass as current ----
for (const name of Object.keys(ANCHORS)) {
  const va = ANCHORS[name];
  out.anchors[name] = { va: '0x' + va.toString(16), bytes: hex(at(va), 24) };
}

// ---- 2. vtable dumps around the two named vtables ----
function dumpVtable(name, vtable_va, before, slots) {
  const start = at(vtable_va - before);
  const rows = [];
  for (let i = 0; i < slots; i++) {
    const slot = start.add(i * 8);
    let fn;
    try { fn = slot.readPointer(); } catch (e) { break; }
    const slot_va = '0x' + slot.sub(base).add(0x140000000).toString(16);
    const row = {
      slot_va,
      slot_off_from_vtable: '0x' + (i * 8 - before).toString(16),
      fn: fn.isNull() ? null : off(fn),
      fn_bytes: fn.isNull() ? null : hex(fn, 16),
    };
    rows.push(row);
  }
  out.vtables[name] = { vtable_va: '0x' + vtable_va.toString(16), rows };
}
dumpVtable('player_mgr_0x1484fdb78', 0x1484FDB78, 0x80, 48);
dumpVtable('processor_0x148590ab8', 0x148590AB8, 0, 40);

// ---- 3. log format strings in the loaded image ----
const ranges = mod.enumerateRanges('r--');
out.range_count = ranges.length;
out.ranges = ranges.map((r) => ({ base: r.base.toString(), size: r.size, prot: r.protection }));

for (const s of LOG_STRINGS) {
  const bytes = [];
  for (let i = 0; i < s.length; i++) bytes.push(s.charCodeAt(i) & 0xff);
  const hits = [];
  for (const r of ranges) {
    if (r.size > 0x40000000) continue;
    let found = [];
    try { found = Memory.scanSync(r.base, r.size, pattern(bytes)); } catch (e) { continue; }
    for (const f of found) hits.push(off(f.address));
    if (hits.length > 24) break;
  }
  out.log_strings[s] = hits.slice(0, 24);
}

// ---- 4. pointers to the anchor code: these are the vtables that name it ----
for (const name of Object.keys(POINTER_TARGETS)) {
  const va = POINTER_TARGETS[name];
  const pat = pattern(le64(va));
  const hits = [];
  for (const r of ranges) {
    if (r.size > 0x40000000) continue;
    let found = [];
    try { found = Memory.scanSync(r.base, r.size, pat); } catch (e) { continue; }
    for (const f of found) hits.push(off(f.address));
    if (hits.length > 64) break;
  }
  out.pointer_hits[name] = hits.slice(0, 64);
}

// ---- 5. how many slots in the image equal the generic dispatch target ----
const slot20pat = pattern(le64(0x14029F9F0));
for (const r of ranges) {
  if (r.size > 0x40000000) continue;
  let found = [];
  try { found = Memory.scanSync(r.base, r.size, slot20pat); } catch (e) { continue; }
  for (const f of found) out.slot20_sharers.push(off(f.address));
  if (out.slot20_sharers.length > 64) break;
}
out.slot20_sharers = out.slot20_sharers.slice(0, 64);

send({ ev: 'recon', recon: out });
send({ ev: 'done' });

// Exists so `_paths.safe_shutdown(kill=False)` takes its orderly path. This probe
// installs no hooks, but the export keeps the teardown contract uniform.
rpc.exports = { teardown() { Interceptor.detachAll(); } };
"""


def build_js() -> str:
    # Plain substitution: the agent source contains `%` (modulo) and must not be
    # run through printf-style formatting.
    js = JS
    js = js.replace("__ANCHORS__", json.dumps(ANCHORS))
    js = js.replace("__LOG_STRINGS__", json.dumps(LOG_STRINGS))
    js = js.replace("__POINTER_TARGETS__", json.dumps(POINTER_TARGETS))
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", type=int, default=120)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    require_build(PROBE_BUILD_SHA256, "bundle-handler-recon")

    out = Path(args.out) if args.out else probe_capture("bundle-handler-recon.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {"recon": None}

    def flush() -> None:
        out.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            if payload.get("err"):
                print(f"[probe] {payload['err']}", flush=True)
                return
            if payload.get("ev") == "recon":
                state["recon"] = payload["recon"]
                flush()
                print("[probe] recon received", flush=True)
            elif payload.get("ev") == "done":
                state["done"] = True
                flush()
                print("[probe] done", flush=True)
        else:
            print(f"[probe:{msg.get('type')}] {msg.get('description') or msg}", flush=True)

    device = frida.get_local_device()
    session = device.attach("NewWorld.exe")
    script = session.create_script(build_js())
    script.on("message", on_msg)
    script.load()

    deadline = time.time() + args.wait
    while time.time() < deadline and not state.get("done"):
        time.sleep(0.5)

    flush()
    print(f"[probe] recon -> {out}", flush=True)
    # No hooks are installed by this probe, so an orderly detach is safe and the
    # client survives for the measurement probe that follows.
    strategy = safe_shutdown(session, script, kill=False, device=device)
    print(f"[probe] shutdown: {strategy}", flush=True)
    return 0 if state.get("recon") else 1


if __name__ == "__main__":
    raise SystemExit(main())
