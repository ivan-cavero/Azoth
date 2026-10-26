#!/usr/bin/env python3
"""Find the code that emits a Game.log line by hooking the file write itself.

WHY THIS EXISTS
===============
The 0x8 handler cannot be found by xref (handlers are reached through virtual
slots) and cannot be found from the log strings either: measured in this session,
`HandleUnexpectedMessage skipping ReceiveStateBundle ...` at `.rdata`
`0x1485006f0` has NO rip-relative reference, NO imm64 reference and NO pointer
table entry anywhere in the loaded image, so the "resolve the format string"
route is closed on this build.

What is left is the other end of the same fact: the client writes that line to
`Game.log`. Hooking the write primitive captures the text and the call stack that
produced it, which names the logging function and the function that decided to log
-- i.e. the bundle receive/apply path, arrived at from behaviour rather than from
a guessed address.

Two write primitives are hooked, because which one the engine uses is not known
here: the C runtime `fwrite`/`fputs`/`_write` family and `WriteFile`. Whichever
fires is the answer, and the capture says which.

The client's own log is the ground truth this probe is checked against: a hook
that is live must report the same lines the log contains, with the same
timestamps around them.

Usage:
    python -u reverse/probes/client/frida-log-write-backtrace.py --seconds 180
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

KEYWORDS = [
    "ReceiveStateBundle",
    "HandleUnexpectedMessage",
    "ProcessPendingReliableMsgQueue",
    "clientContext->Initialize",
    "player spawn succeeds",
    "Failed to unmarshal",
    "ValidationError",
    "WaitingForPlayerSpawn",
    "GameMessagePort",
]

JS = r"""
const KEYWORDS = __KEYWORDS__;
const MAX_RECORDS = __MAX_RECORDS__;

const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const off = (p) => {
  try { return '0x' + p.sub(base).add(0x140000000).toString(16); }
  catch (e) { return p.toString(); }
};

let records = 0;
let writes = 0;
const perPrimitive = {};

function readText(p, len) {
  const n = Math.min(len || 0, 2048);
  if (n <= 0) return null;
  try { return p.readUtf8String(n); } catch (e) { return null; }
}

function emit(context, primitive, text, extra) {
  if (!text) return;
  let kw = null;
  for (const k of KEYWORDS) { if (text.indexOf(k) >= 0) { kw = k; break; } }
  if (kw === null) return;
  if (records >= MAX_RECORDS) return;
  records++;
  send({
    ev: 'log',
    primitive,
    kw,
    text: text.slice(0, 700),
    bt: Thread.backtrace(context, Backtracer.ACCURATE).slice(0, 14).map(off),
    ...extra,
  });
}

function hookExport(names, maker) {
  for (const name of names) {
    let addr = null;
    // Frida 17 dropped the global `Module` helper; resolve through the owning
    // module instead, which also keeps the DLL name explicit in the capture.
    const owners = ['msvcrt.dll', 'ucrtbase.dll', 'kernel32.dll', 'api-ms-win-crt-stdio-l1-1-0.dll'];
    for (const owner of owners) {
      const m = Process.findModuleByName(owner);
      if (!m) continue;
      try { addr = m.getExportByName(name); } catch (e) { addr = null; }
      if (addr) {
        send({ ev: 'resolved', name, owner, addr: addr.toString() });
        break;
      }
    }
    if (!addr) { send({ ev: 'unresolved', name }); continue; }
    try {
      Interceptor.attach(addr, maker(name));
      perPrimitive[name] = 0;
      send({ ev: 'hooked', name, addr: addr.toString() });
      return name;
    } catch (e) {
      send({ ev: 'hook-failed', name, msg: String(e) });
    }
  }
  return null;
}

// fwrite(const void *buffer, size_t size, size_t count, FILE *stream)
hookExport(['fwrite', 'fwrite_nolock'], (name) => ({
  onEnter(args) {
    writes++;
    perPrimitive[name] = (perPrimitive[name] || 0) + 1;
    let len = 0;
    try { len = args[1].toInt32() * args[2].toInt32(); } catch (e) {}
    emit(this.context, name, readText(args[0], len), { len });
  },
}));

// fputs(const char *s, FILE *stream)
hookExport(['fputs'], (name) => ({
  onEnter(args) {
    writes++;
    perPrimitive[name] = (perPrimitive[name] || 0) + 1;
    emit(this.context, name, readText(args[0], 1024), {});
  },
}));

// WriteFile(HANDLE, LPCVOID buf, DWORD n, LPDWORD written, LPOVERLAPPED)
hookExport(['WriteFile', 'WriteFileImplementation'], (name) => ({
  onEnter(args) {
    writes++;
    perPrimitive[name] = (perPrimitive[name] || 0) + 1;
    let len = 0;
    try { len = args[2].toInt32(); } catch (e) {}
    emit(this.context, name, readText(args[1], len), { len });
  },
}));

// _write(int fd, const void *buf, unsigned n)
hookExport(['_write'], (name) => ({
  onEnter(args) {
    writes++;
    perPrimitive[name] = (perPrimitive[name] || 0) + 1;
    let len = 0;
    try { len = args[2].toInt32(); } catch (e) {}
    emit(this.context, name, readText(args[1], len), { len });
  },
}));

send({ ev: 'ready', primitives: Object.keys(perPrimitive) });

rpc.exports = {
  teardown() { Interceptor.detachAll(); },
  counters() { return { writes, records, perPrimitive }; },
};
"""


def build_js(max_records: int) -> str:
    js = JS
    js = js.replace("__KEYWORDS__", json.dumps(KEYWORDS))
    js = js.replace("__MAX_RECORDS__", str(max_records))
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--max-records", type=int, default=400)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    require_build(PROBE_BUILD_SHA256, "log-write-backtrace")

    out = Path(args.out) if args.out else probe_capture("log-write-backtrace.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")
    state = {"records": 0}

    def flush_row(row: dict) -> None:
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            ev = payload.get("ev")
            if ev == "log":
                state["records"] += 1
                flush_row(payload)
                print(f"[probe] log kw={payload['kw']} via {payload['primitive']}: "
                      f"{payload['text'][:160]!r}", flush=True)
            elif ev in ("hooked", "hook-failed", "ready"):
                flush_row(payload)
                print(f"[probe] {ev} {payload}", flush=True)
        else:
            print(f"[probe:{msg.get('type')}] {msg.get('description') or msg}", flush=True)

    device = frida.get_local_device()
    session = device.attach("NewWorld.exe")
    script = session.create_script(build_js(args.max_records))
    script.on("message", on_msg)
    script.load()

    started = time.time()
    deadline = started + args.seconds
    last = 0.0
    while time.time() < deadline:
        time.sleep(1)
        now = time.time()
        if now - last >= 10:
            last = now
            try:
                c = script.exports_sync.counters()
                print(f"[probe] t+{int(now - started)}s writes={c['writes']} "
                      f"records={c['records']} per={c['perPrimitive']}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[probe] counters unavailable: {exc}", flush=True)

    try:
        final = script.exports_sync.counters()
    except Exception as exc:  # noqa: BLE001
        final = {"error": str(exc)}
    flush_row({"ev": "final", **final})
    print(f"[probe] final {final}", flush=True)
    print(f"[probe] -> {out}", flush=True)

    strategy = safe_shutdown(session, script, kill=True, device=device)
    print(f"[probe] shutdown: {strategy}", flush=True)
    return 0 if state["records"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
