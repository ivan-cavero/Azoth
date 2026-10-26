#!/usr/bin/env python3
"""Watch the GameMessagePort log strings to find the bundle receive/apply code.

WHY THIS EXISTS
===============
The question is discrete: is the client's wire-type-0x8 `ReplicatedStateBundle`
handler CALLED for the 46,407-byte spawn record? It cannot be answered by xref --
handlers are reached through virtual slots, so no `call` to a handler exists in
the image -- and the two anchors that were supposed to reach it measured ZERO
calls in a live world-entry run while 1015 calls landed on other functions of the
same processor vtable, i.e. the hooks were live and those two addresses were not
on the path.

Measured in this session, the other obvious route is closed too: the rung-17 log
strings in `.rdata` (`HandleUnexpectedMessage skipping ReceiveStateBundle ...`,
`clientContext == nullptr`, `player spawn succeeds`) have NO rip-relative
reference, NO imm64 reference and NO pointer-table entry anywhere in the loaded
image, so the logging call site cannot be found by scanning for the string's
address.

So this probe watches the STRINGS themselves. `MemoryAccessMonitor` on the two
pages that hold the GameMessagePort log cluster reports, for every read, the
accessing instruction address and the exact address read. That names the code that
logs each line -- and the line `HandleUnexpectedMessage skipping ReceiveStateBundle`
is emitted only on the bundle path, so the instruction that reads it sits inside
the function that decides what to do with the bundle.

The strings are used as identifiers here, not as a source of truth about behaviour:
every claim is cross-checked against the client's own Game.log from the same run.

Also hooked, as positive controls so a negative cannot be explained away:
  * 0x146455ec0 / 0x146447ac0 -- the two handlers VERIFIED on 1.460. If these fire
    in the same run, the hook mechanism itself is proven live.
  * 0x146b6ea20 / 0x14029f9f0 -- the supplied decode entry and +0x20 forwarder.
  * every distinct function of the player-manager vtable 0x1484fdb78, counted, so
    a "nothing fired" answer comes with the list of what did fire.

Usage:
    python -u reverse/probes/client/frida-bundle-log-string-watch.py --seconds 175
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

# Pages holding the GameMessagePort / GameConnection log-string cluster, read live
# by frida-log-string-diag.py. 0x1484ff000 also holds "player spawn succeeds".
WATCH_RANGES = [
    [0x1484FF000, 0x1000],
    [0x148500000, 0x1000],
]

# Strings of interest, so an access can be named instead of reported as a number.
STRING_MAP = {
    0x1484FFEFF: "GameConnectionWrapper: player spawn succeeds, in game",
    0x1484FFF20: " BannedUntilEpochMS: ",
    0x1484FFF38: "Report Error: Reason: ",
    0x1484FFF50: "%d, Connection State %d, ...",
    0x1484FFFD8: " countReceived: ",
    0x1484FFFF0: "GameConnectionWrapper::OnRemoteNetworkConnectionWarning",
    0x148500060: "client_connection_error",
    0x1485006F0: "HandleUnexpectedMessage skipping ReceiveStateBundle ... clientContext == nullptr",
    0x148500760: "HandleUnexpectedMessage received bundle for a previous ClientContext",
    0x1485007C0: "HandleUnexpectedMessage failed - unable to handle message of type",
    0x148500810: "Switch coming from clientContextInstanceId %d to m_clientContextInstanceId %d",
    0x148500860: "MayHandleReplicationUnreliable() returning false",
    0x1485008F8: "LoadContextAndLevel failed - no self identification",
    0x148500930: "LoadContextAndLevel failed - missing LevelInfo",
    0x148500960: "LoadContextAndLevel failed - pGame is nullptr",
    0x148500990: "LoadContextAndLevel failed - clientSdk is nullptr",
    0x1485009C8: "Calling clientContext->Initialize",
    0x1485009F0: "ProcessPendingReliableMsgQueue processing %zu messages from m_pendingUnexpectedMsgs",
    0x148500A48: " message seqs=[",
    0x148500A58: "; next ",
    0x148500A60: "; m_pendingReliableReplicationMsgs size=",
    0x148500A90: ". ClientContextInstanceId=",
    0x148500AB0: ". Expected seq=",
    0x148500AC0: "secs for replication message at time ",
    0x148500AE8: "Timed out waiting ",
    0x148500AF8: "(seq=",
    0x148500B14: "PlayerManagerSelfIdentification",
    0x148500D28: "LevelInfoChanged",
}

# Verified 1.460 anchors and the two supplied dispatch anchors.
CONTROL_HOOKS = {
    "handler_0x65c": 0x146455EC0,     # VERIFIED 1.460: decoded struct read back
    "handler_0x663": 0x146447AC0,     # VERIFIED 1.460
    "inbound_decode_entry": 0x146B6EA20,
    "processor_slot_plus20": 0x14029F9F0,
}

# Distinct functions of the player-manager vtable 0x1484fdb78, read live.
PLAYER_MGR_VTABLE_FNS = [
    0x14645BF44, 0x1407C3170, 0x14643B488, 0x14645D8B0, 0x14642E484,
    0x14642E4C4, 0x14642E3BC, 0x14642E444, 0x14642E404, 0x14642E504,
    0x14645D914, 0x146471B5C, 0x146471B34, 0x14643B468, 0x14645D510,
    0x14645D5FC, 0x146455EAC, 0x146455C5C, 0x146447AA8, 0x14645EF0C,
    0x14642E090, 0x14643B4B0, 0x1414D8A1C, 0x1407C5A60, 0x146447420,
    0x146471EC8, 0x140294A00, 0x1414CCFC0, 0x146450DD0, 0x146450B5C,
]

JS = r"""
const WATCH_RANGES = __WATCH_RANGES__;
const STRING_MAP = __STRING_MAP__;
const CONTROL_HOOKS = __CONTROL_HOOKS__;
const PLAYER_MGR_VTABLE_FNS = __PLAYER_MGR_VTABLE_FNS__;
const MAX_ACCESS = __MAX_ACCESS__;

const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
const off = (p) => {
  try { return '0x' + p.sub(base).add(0x140000000).toString(16); }
  catch (e) { return String(p); }
};

function hex(p, n) {
  try {
    const b = new Uint8Array(p.readByteArray(n));
    return Array.from(b).map((x) => x.toString(16).padStart(2, '0')).join(' ');
  } catch (e) { return null; }
}

function nameString(va) {
  // Nearest string start at or below the accessed address.
  let best = null;
  let bestVa = -1;
  for (const k of Object.keys(STRING_MAP)) {
    const v = parseInt(k, 10);
    if (v <= va && v > bestVa) { bestVa = v; best = STRING_MAP[k]; }
  }
  return best;
}

const t0 = Date.now();
let accesses = 0;
let armed = false;

function arm() {
  if (armed || accesses >= MAX_ACCESS) return;
  armed = true;
  try {
    MemoryAccessMonitor.enable(
      WATCH_RANGES.map(([va, size]) => ({ base: at(va), size })),
      {
        onAccess(details) {
          armed = false;
          accesses++;
          const from = off(details.from);
          const addr = parseInt(details.address.toString(), 16);
          const rva = addr - parseInt(base.toString(), 16) + 0x140000000;
          send({
            ev: 'access',
            n: accesses,
            ms: Date.now() - t0,
            op: details.operation,
            from,
            addr: '0x' + rva.toString(16),
            string: nameString(rva),
            insn_bytes: hex(details.from, 16),
            // The instruction's own displacement, when it is rip-relative.
            from_bytes: hex(details.from.sub(12), 28),
          });
          arm();
        }
      }
    );
  } catch (e) {
    send({ ev: 'arm-error', msg: String(e) });
  }
}

// ---- controls: counters only ----
const controlCounts = {};
for (const name of Object.keys(CONTROL_HOOKS)) {
  const va = CONTROL_HOOKS[name];
  controlCounts[name] = 0;
  try {
    Interceptor.attach(at(va), { onEnter() { controlCounts[name]++; } });
  } catch (e) {
    send({ ev: 'hook-error', name, msg: String(e) });
  }
}

const mgrCounts = {};
for (const va of PLAYER_MGR_VTABLE_FNS) {
  const key = '0x' + va.toString(16);
  mgrCounts[key] = 0;
  try {
    Interceptor.attach(at(va), { onEnter() { mgrCounts[key]++; } });
  } catch (e) {
    send({ ev: 'hook-error', name: key, msg: String(e) });
  }
}

send({ ev: 'ready',
       ranges: WATCH_RANGES.map(([va, size]) => ['0x' + va.toString(16), size]),
       controls: Object.keys(controlCounts),
       mgr_hooked: Object.keys(mgrCounts).length });

arm();

rpc.exports = {
  teardown() {
    try { MemoryAccessMonitor.disable(); } catch (e) {}
    Interceptor.detachAll();
  },
  counters() { return { accesses, controlCounts, mgrCounts }; },
};
"""


def build_js(max_access: int) -> str:
    js = JS
    js = js.replace("__WATCH_RANGES__", json.dumps(WATCH_RANGES))
    js = js.replace("__STRING_MAP__", json.dumps(STRING_MAP))
    js = js.replace("__CONTROL_HOOKS__", json.dumps(CONTROL_HOOKS))
    js = js.replace("__PLAYER_MGR_VTABLE_FNS__", json.dumps(PLAYER_MGR_VTABLE_FNS))
    js = js.replace("__MAX_ACCESS__", str(max_access))
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=int, default=175)
    ap.add_argument("--max-access", type=int, default=400)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    require_build(PROBE_BUILD_SHA256, "bundle-log-string-watch")

    out = Path(args.out) if args.out else probe_capture("bundle-log-string-watch.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")
    state = {"accesses": 0}

    def flush_row(row: dict) -> None:
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            ev = payload.get("ev")
            if ev == "access":
                state["accesses"] += 1
                flush_row(payload)
                print(f"[probe] access #{payload['n']} t+{payload['ms']}ms "
                      f"{payload['op']} from {payload['from']} "
                      f"string={payload['string']!r} bytes={payload['insn_bytes']}",
                      flush=True)
            elif ev in ("ready", "arm-error", "hook-error"):
                flush_row(payload)
                print(f"[probe] {ev} {payload}", flush=True)
        else:
            print(f"[probe:{msg.get('type')}] {msg.get('description') or msg}", flush=True)

    device = frida.get_local_device()
    session = device.attach("NewWorld.exe")
    script = session.create_script(build_js(args.max_access))
    script.on("message", on_msg)
    script.load()

    started = time.time()
    deadline = started + args.seconds
    last = 0.0
    while time.time() < deadline:
        time.sleep(1)
        now = time.time()
        if now - last >= 15:
            last = now
            try:
                c = script.exports_sync.counters()
                fired = {k: v for k, v in c["controlCounts"].items() if v}
                mgrf = {k: v for k, v in c["mgrCounts"].items() if v}
                print(f"[probe] t+{int(now - started)}s accesses={c['accesses']} "
                      f"controls_fired={fired} mgr_fired={mgrf}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[probe] counters unavailable: {exc}", flush=True)

    try:
        final = script.exports_sync.counters()
    except Exception as exc:  # noqa: BLE001
        final = {"error": str(exc)}
    flush_row({"ev": "final", **final})
    print(f"[probe] final {json.dumps(final)[:2000]}", flush=True)
    print(f"[probe] -> {out}", flush=True)

    strategy = safe_shutdown(session, script, kill=True, device=device)
    print(f"[probe] shutdown: {strategy}", flush=True)
    return 0 if state["accesses"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
