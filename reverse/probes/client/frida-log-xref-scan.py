#!/usr/bin/env python3
"""Find the code that emits the rung-17 log lines, by scanning the loaded image.

WHY THIS EXISTS
===============
The 0x8 handler cannot be found by xref: the decode entry `0x146b6ea20` reaches
handlers through a virtual slot, so no `call` to a handler exists in the image.
The rung-17 evidence in `research/atlas/meanings.md` quotes log lines the client
prints on exactly the path in question:

    HandleUnexpectedMessage skipping ReceiveStateBundle for bundle message
    due to clientContext == nullptr
    ProcessPendingReliableMsgQueue processing N messages from m_pendingUnexpectedMsgs
    Calling clientContext->Initialize
    player spawn succeeds
    Failed to unmarshal
    ValidationError

A pointer to one of those format strings is a direct handle on the function that
prints it. That function is the bundle receive/apply decision point, which is a
second route to the handler that does not depend on any vtable guess -- and a
route that can be checked, because its hits must be consistent with the log the
client actually wrote.

The scan is `lea reg,[rip+disp32]` / `mov reg,[rip+disp32]` over the loaded r-x
range, keeping only references that land inside the log-string windows. False
positives are excluded by construction: a stray byte sequence that happens to look
like a lea would have to point at a 4-byte-exact offset inside a known string.

This reads the running process. Nothing is opened as a file and no decompiler or
static analyser touches the private copy.

Usage:
    python -u reverse/probes/client/frida-log-xref-scan.py
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

# Windows around the log strings located by frida-bundle-handler-recon.py.
STRING_WINDOWS = [
    ["game_message_port_logs", 0x1484FFE00, 0x148500B00],
    ["failed_to_unmarshal_a", 0x1484D7400, 0x1484D7500],
    ["failed_to_unmarshal_b", 0x148592580, 0x148592700],
    ["validation_error_a", 0x1481589C0, 0x148158A80],
    ["validation_error_b", 0x1484CA340, 0x1484CA420],
    ["validation_error_c", 0x1486FD980, 0x1486FDA40],
    ["local_player_metadata", 0x148042900, 0x148042A00],
]

# Region dumps, so the vtable neighbourhood around the decode entry can be read.
DUMP_REGIONS = [
    ["vtable_after_processor", 0x148590B00, 0x148592100],
    ["static_object_table", 0x147EFA100, 0x147EFA700],
    ["player_mgr_vtable_tail", 0x1484FDC00, 0x1484FDE00],
]

# rip-relative forms worth resolving: lea r64 (with/without REX.W) and mov r64.
PATTERNS = []
for modrm in (0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D):
    PATTERNS.append(["8d %02x" % modrm, 6])
    PATTERNS.append(["48 8d %02x" % modrm, 7])
    PATTERNS.append(["4c 8d %02x" % modrm, 7])
    PATTERNS.append(["48 8b %02x" % modrm, 7])

JS = r"""
const STRING_WINDOWS = __WINDOWS__;
const DUMP_REGIONS = __REGIONS__;
const PATTERNS = __PATTERNS__;

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

// ---- region dumps ----
const regions = {};
for (const [name, lo, hi] of DUMP_REGIONS) {
  const rows = [];
  for (let va = lo; va < hi; va += 8) {
    let v = null;
    try { v = rt(va).readPointer(); } catch (e) { v = null; }
    rows.push({ va: '0x' + va.toString(16), qword: v ? v.toString() : null });
  }
  regions[name] = { lo: '0x' + lo.toString(16), hi: '0x' + hi.toString(16), rows };
}
send({ ev: 'regions', regions });

// ---- xref scan ----
const text = mod.enumerateRanges('r-x')[0];
const hits = [];
let done = 0;

function windowOf(target) {
  for (const [name, lo, hi] of STRING_WINDOWS) {
    if (target >= lo && target < hi) return name;
  }
  return null;
}

function scanPattern(idx) {
  return new Promise((resolve) => {
    if (idx >= PATTERNS.length) { resolve(); return; }
    const [pat, insnLen] = PATTERNS[idx];
    let matched = 0;
    Memory.scan(text.base, text.size, pat, {
      onMatch(address) {
        matched++;
        const a = parseInt(address.toString(), 16);
        let disp;
        try { disp = address.add(insnLen - 4).readS32(); } catch (e) { resolve(); return; }
        const target = a + insnLen + disp;
        const w = windowOf(target);
        if (w !== null) {
          hits.push({
            insn: off(address),
            pattern: pat,
            target: '0x' + target.toString(16),
            window: w,
            target_bytes: hex(rt(target), 48),
          });
        }
      },
      onComplete() {
        done++;
        resolve();
      },
    });
  });
}

(async () => {
  for (let i = 0; i < PATTERNS.length; i++) await scanPattern(i);
  send({ ev: 'xrefs', hits, patterns: PATTERNS.length,
         text_base: off(text.base), text_size: text.size });
  send({ ev: 'done' });
})();

rpc.exports = { teardown() { Interceptor.detachAll(); } };
"""


def build_js() -> str:
    js = JS
    js = js.replace("__WINDOWS__", json.dumps(STRING_WINDOWS))
    js = js.replace("__REGIONS__", json.dumps(DUMP_REGIONS))
    js = js.replace("__PATTERNS__", json.dumps(PATTERNS))
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", type=int, default=600)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    require_build(PROBE_BUILD_SHA256, "log-xref-scan")

    out = Path(args.out) if args.out else probe_capture("log-xref-scan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {"xrefs": None, "regions": None}

    def flush() -> None:
        out.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            ev = payload.get("ev")
            if ev == "regions":
                state["regions"] = payload["regions"]
                flush()
                print("[probe] regions dumped", flush=True)
            elif ev == "xrefs":
                state["xrefs"] = payload
                flush()
                print(f"[probe] xref hits: {len(payload['hits'])} "
                      f"over {payload['patterns']} patterns", flush=True)
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
    return 0 if state.get("xrefs") else 1


if __name__ == "__main__":
    raise SystemExit(main())
