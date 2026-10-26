#!/usr/bin/env python3
"""Watch the inbound dispatch path and discover the handler each message reaches.

WHY THIS EXISTS
===============
Rung 17 is measured as "accept and wait": the client decodes the 46,407-byte
wire-type-0x8 spawn record with zero `Failed to unmarshal` and zero
`ValidationError`, then expires. Whether the client's 0x8 handler is ever CALLED
for that record is the unmeasured half, and it cannot be answered from an xref:
the decode entry reaches handlers through a virtual slot, so no `call` to a
handler exists in the image. Measured here (see `log-xref-scan` /
`log-string-diag`): the rung-17 log strings in `.rdata` have NO rip-relative, no
imm64 and no pointer-table reference anywhere in the loaded image, so the
"find the logging function" route is also closed.

What is left is to read the dispatch as it happens, from the two anchors that are
VERIFIED on 1.460:

  0x146b6ea20  inbound decode entry
  0x14029f9f0  target of stream-processor vtable slot +0x20

The second one is the useful one, and its own prologue says what it is:

    push rbx; sub rsp,0x20; mov rax,[rdx]; mov rcx,rdx; mov rbx,rdx; call [rax+0x60]

It is a **forwarder**: it takes the message object in `rdx` and calls that
object's own virtual slot `+0x60`. So the per-message handler is `[[rdx]+0x60]`,
and it is discovered here rather than guessed -- each distinct target is attached
the first time it is seen, and its calls are counted and recorded.

That converts the open question into a discrete measurement: for the run, which
handler addresses were reached, how many times, and did any of them run while a
46,407-byte record was in flight.

ATTACH AT CHARACTER SELECT. The shutdown helper kills the client on purpose, so
attaching at launch would make every wait expire with misleading symptoms.

Usage:
    python -u reverse/probes/client/frida-bundle-handler-watch.py --seconds 170
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

# private-client/runtime/Bin64/NewWorld.exe
PROBE_BUILD_SHA256 = "97f17df315aef97bed1303bb9d57330be67e9e0c9e22acb59dde68de837b743c"

DECODE_ENTRY = 0x146B6EA20     # verified 1.460 anchor
DISPATCH_THUNK = 0x14029F9F0   # verified 1.460 anchor, processor vtable slot +0x20

# Distinct functions of the stream-processor vtable 0x148590ab8, read live by
# frida-bundle-handler-recon.py. Hooked as cheap counters so the run shows which
# processor methods are live at all -- if none fire, the vtable is not the path.
PROCESSOR_VTABLE_FNS = [
    0x1402A0100, 0x14029E840, 0x14029F6F0, 0x146B5E0A0, 0x14029F8D0,
    0x146B5E360, 0x14029F840, 0x145DE9E40, 0x14029F570, 0x146B5E1F0,
    0x14029F900, 0x146B5E480,
]

JS = r"""
const DECODE_ENTRY = __DECODE_ENTRY__;
const DISPATCH_THUNK = __DISPATCH_THUNK__;
const PROCESSOR_VTABLE_FNS = __PROCESSOR_VTABLE_FNS__;

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

let seq = 0;
const counters = { decode: 0, dispatch: 0, handler: 0, processor: 0 };
const handlerCounts = {};   // va -> calls
const processorCounts = {};
const hooked = new Set();
const MAX_RECORDS = __MAX_RECORDS__;
let records = 0;

function record(row) {
  if (records >= MAX_RECORDS) return;
  records++;
  send({ ev: 'rec', row });
}

function attachHandler(va) {
  const key = va.toString();
  if (hooked.has(key)) return;
  hooked.add(key);
  handlerCounts[key] = 0;
  try {
    Interceptor.attach(ptr(key), {
      onEnter(args) {
        counters.handler++;
        handlerCounts[key]++;
        if (records >= MAX_RECORDS) return;
        const obj = args[0];
        record({
          s: ++seq, t: 'handler', va: key, n: handlerCounts[key],
          this: obj.toString(),
          a1: args[1].toString(), a2: args[2].toString(), a3: args[3].toString(),
          head: hex(obj, 64),
          vt: (() => { try { return off(obj.readPointer()); } catch (e) { return null; } })(),
        });
      },
    });
  } catch (e) {
    send({ ev: 'err', what: 'attachHandler', va: key, msg: String(e) });
  }
}

// ---- decode entry ----
Interceptor.attach(at(DECODE_ENTRY), {
  onEnter(args) {
    counters.decode++;
    if (records >= MAX_RECORDS) return;
    const a0 = args[0];
    let vt = null, head = null;
    try { vt = off(a0.readPointer()); head = hex(a0, 64); } catch (e) {}
    record({
      s: ++seq, t: 'decode', n: counters.decode,
      this: a0.toString(),
      a1: args[1].toString(), a2: args[2].toString(), a3: args[3].toString(),
      vt, head,
      bt: Thread.backtrace(this.context, Backtracer.ACCURATE).slice(0, 6).map(off),
    });
  },
});

// ---- dispatch forwarder: the per-message handler is [[rdx]+0x60] ----
Interceptor.attach(at(DISPATCH_THUNK), {
  onEnter(args) {
    counters.dispatch++;
    const obj = args[1];
    let vt = null, handler = null, head = null;
    try {
      vt = obj.readPointer();
      handler = vt.add(0x60).readPointer();
      head = hex(obj, 96);
    } catch (e) {}
    if (handler) attachHandler(handler);
    if (records >= MAX_RECORDS) return;
    record({
      s: ++seq, t: 'dispatch', n: counters.dispatch,
      this: args[0].toString(), obj: obj.toString(),
      vt: vt ? off(vt) : null,
      handler: handler ? off(handler) : null,
      head,
    });
  },
});

// ---- processor vtable counters (context, not the answer) ----
for (const va of PROCESSOR_VTABLE_FNS) {
  const key = '0x' + va.toString(16);
  processorCounts[key] = 0;
  try {
    Interceptor.attach(at(va), {
      onEnter(args) {
        counters.processor++;
        processorCounts[key]++;
      },
    });
  } catch (e) {
    send({ ev: 'err', what: 'attachProcessor', va: key, msg: String(e) });
  }
}

send({ ev: 'ready',
       decode_entry: off(at(DECODE_ENTRY)),
       dispatch_thunk: off(at(DISPATCH_THUNK)),
       processor_hooked: Object.keys(processorCounts).length,
       max_records: MAX_RECORDS });

rpc.exports = {
  teardown() { Interceptor.detachAll(); },
  counters() {
    return { counters, handlerCounts, processorCounts, records };
  },
};
"""


def build_js(max_records: int) -> str:
    js = JS
    js = js.replace("__DECODE_ENTRY__", hex(DECODE_ENTRY))
    js = js.replace("__DISPATCH_THUNK__", hex(DISPATCH_THUNK))
    js = js.replace("__PROCESSOR_VTABLE_FNS__", json.dumps(PROCESSOR_VTABLE_FNS))
    js = js.replace("__MAX_RECORDS__", str(max_records))
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=int, default=170)
    ap.add_argument("--max-records", type=int, default=4000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    require_build(PROBE_BUILD_SHA256, "bundle-handler-watch")

    out = Path(args.out) if args.out else probe_capture("bundle-handler-watch.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")
    state: dict = {"ready": None, "records": 0}

    def flush_row(row: dict) -> None:
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            ev = payload.get("ev")
            if ev == "ready":
                state["ready"] = payload
                flush_row({"ev": "ready", **payload})
                print(f"[probe] ready {payload}", flush=True)
            elif ev == "rec":
                state["records"] += 1
                flush_row(payload["row"])
                row = payload["row"]
                if row["t"] != "handler" or row.get("n") == 1:
                    print(f"[probe] {row['t']} #{row['n']} {row}", flush=True)
            elif ev == "err":
                print(f"[probe:err] {payload}", flush=True)
                flush_row({"ev": "err", **payload})
        else:
            print(f"[probe:{msg.get('type')}] {msg.get('description') or msg}", flush=True)

    device = frida.get_local_device()
    session = device.attach("NewWorld.exe")
    script = session.create_script(build_js(args.max_records))
    script.on("message", on_msg)
    script.load()

    started = time.time()
    deadline = started + args.seconds
    last_report = 0.0
    while time.time() < deadline:
        time.sleep(1)
        now = time.time()
        if now - last_report >= 10:
            last_report = now
            try:
                c = script.exports_sync.counters()
                print(f"[probe] t+{int(now - started)}s counters={c['counters']} "
                      f"records={c['records']} handlers={c['handlerCounts']}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[probe] counters unavailable: {exc}", flush=True)

    counters = {}
    try:
        counters = script.exports_sync.counters()
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] final counters unavailable: {exc}", flush=True)
    flush_row({"ev": "final", **counters})
    print(f"[probe] final {counters}", flush=True)
    print(f"[probe] -> {out}", flush=True)

    # kill=True: deliberate, so no agent-unload race can be misread as client behaviour.
    strategy = safe_shutdown(session, script, kill=True, device=device)
    print(f"[probe] shutdown: {strategy}", flush=True)
    return 0 if state["records"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
