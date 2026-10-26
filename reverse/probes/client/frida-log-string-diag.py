#!/usr/bin/env python3
"""Diagnose why no rip-relative xref to the rung-17 log strings was found.

WHY THIS EXISTS
===============
`frida-log-xref-scan.py` resolved zero `lea reg,[rip+disp32]` / `mov
reg,[rip+disp32]` references to any log string in the loaded image. Zero is a
result that needs an explanation before it can be believed: either the client does
not address those strings that way, or the scanner is broken.

So this probe separates the two, without assuming which:

  1. Scanner sanity: count raw matches for one rip-relative pattern in the loaded
     r-x range, and resolve a *self-test* case -- a `lea` whose target is checked
     against the bytes it points at. A scanner that reports 0 raw matches for
     `48 8d 0d` in 133 MB of code is broken, not informative.
  2. Alternative addressing: scan the whole image for the 8-byte little-endian
     value of each string address. That finds `mov reg, imm64` loads and any
     pointer table entry that names the string, which is where MSVC-style logging
     tables keep their messages.
  3. Structure: dump the bytes around the string cluster so the layout (a bare
     literal, or a record with a level/category field) can be read off directly.

Usage:
    python -u reverse/probes/client/frida-log-string-diag.py
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

STRING_ADDRS = {
    "HandleUnexpectedMessage": 0x1485006F0,
    "skipping_ReceiveStateBundle": 0x148500708,
    "clientContext_nullptr": 0x14850073E,
    "ReceiveStateBundle": 0x148500711,
    "ProcessPendingReliableMsgQueue": 0x1485009F0,
    "Calling_clientContext_Initialize": 0x1485009C8,
    "m_pendingUnexpectedMsgs": 0x148500A2C,
    "player_spawn_succeeds": 0x1484FFEFF,
}

DUMP_WINDOWS = [
    ["game_message_port_logs", 0x1484FFE00, 0x148501200],
]

JS = r"""
const STRING_ADDRS = __ADDRS__;
const DUMP_WINDOWS = __WINDOWS__;

const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const off = (p) => '0x' + p.sub(base).add(0x140000000).toString(16);
const rt = (va) => base.add(va - 0x140000000);

function hex(p, n) {
  try {
    const b = new Uint8Array(p.readByteArray(n));
    return Array.from(b).map((x) => x.toString(16).padStart(2, '0')).join(' ');
  } catch (e) { return null; }
}

function ascii(p, n) {
  try { return p.readCString(n); } catch (e) { return null; }
}

const out = { dumps: {}, self_test: {}, imm64_or_table: {} };

// ---- 3. structure around the log strings ----
for (const [name, lo, hi] of DUMP_WINDOWS) {
  const rows = [];
  for (let va = lo; va < hi; va += 16) {
    rows.push({ va: '0x' + va.toString(16),
                bytes: hex(rt(va), 16),
                ascii: ascii(rt(va), 16) });
  }
  out.dumps[name] = rows;
}

const rw = mod.enumerateRanges('r--');
const rx = mod.enumerateRanges('r-x');
const text = rx[0];
out.text = { base: off(text.base), size: text.size };

// ---- 1. scanner sanity ----
const counts = {};
for (const pat of ['48 8d 0d', '48 8d 15', '48 8b 05', '48 b8', '48 8d']) {
  let n = 0;
  try {
    const found = Memory.scanSync(text.base, Math.min(text.size, 0x4000000), pat);
    n = found.length;
  } catch (e) { n = -1; }
  counts[pat] = { matches_in_first_64MB: n };
}
out.self_test.counts = counts;

// Resolve one lea by hand: find any '48 8d 0d' and print where it points, so a
// reader can confirm the displacement arithmetic independently.
try {
  const probe = Memory.scanSync(text.base, 0x2000000, '48 8d 0d');
  out.self_test.resolved_lea_samples = probe.slice(0, 5).map((m) => {
    const a = parseInt(m.address.toString(), 16);
    const disp = m.address.add(3).readS32();
    const target = a + 7 + disp;
    return { insn: off(m.address), disp, target: '0x' + target.toString(16),
             target_bytes: hex(ptr('0x' + target.toString(16)), 24),
             target_ascii: ascii(ptr('0x' + target.toString(16)), 24) };
  });
  out.self_test.raw_match_count_sampled = probe.length;
} catch (e) {
  out.self_test.error = String(e);
}

// ---- 2. imm64 loads / pointer tables naming the strings ----
for (const name of Object.keys(STRING_ADDRS)) {
  const va = STRING_ADDRS[name];
  const p = rt(va);
  const n = parseInt(p.toString(), 16);
  const bytes = [];
  let v = n;
  for (let i = 0; i < 8; i++) { bytes.push(v % 256); v = Math.floor(v / 256); }
  const pat = bytes.map((x) => x.toString(16).padStart(2, '0')).join(' ');
  const hits = [];
  for (const r of rw.concat(rx)) {
    if (r.size > 0x40000000) continue;
    let found = [];
    try { found = Memory.scanSync(r.base, r.size, pat); } catch (e) { continue; }
    for (const f of found) hits.push(off(f.address));
    if (hits.length > 32) break;
  }
  out.imm64_or_table[name] = hits.slice(0, 32);
}

send({ ev: 'diag', diag: out });
send({ ev: 'done' });

rpc.exports = { teardown() { Interceptor.detachAll(); } };
"""


def build_js() -> str:
    js = JS
    js = js.replace("__ADDRS__", json.dumps(STRING_ADDRS))
    js = js.replace("__WINDOWS__", json.dumps(DUMP_WINDOWS))
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", type=int, default=600)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    require_build(PROBE_BUILD_SHA256, "log-string-diag")

    out = Path(args.out) if args.out else probe_capture("log-string-diag.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {"diag": None}

    def flush() -> None:
        out.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            ev = payload.get("ev")
            if ev == "diag":
                state["diag"] = payload["diag"]
                flush()
                print("[probe] diag received", flush=True)
            elif ev == "done":
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
        time.sleep(1)

    flush()
    print(f"[probe] -> {out}", flush=True)
    strategy = safe_shutdown(session, script, kill=False, device=device)
    print(f"[probe] shutdown: {strategy}", flush=True)
    return 0 if state.get("diag") else 1


if __name__ == "__main__":
    raise SystemExit(main())
