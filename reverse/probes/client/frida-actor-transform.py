#!/usr/bin/env python3
"""Which captured actor id does the client actually hold, and does it carry a transform?

WHY THIS EXISTS, and it is the question the entity work never answered. The roadmap's remaining
lever is "move a body that renders". Two arms on 2026-10-20 showed that neither character record
this project has been rewriting is such a body: record 29 (seq 0xa1) is accepted and does not render,
and Saradnax's record (0x97) declares its slice with no transform at all. So the next step is not
another payload shape - it is to ask the CLIENT which actor id it bound to a rendered slice, and
where that entity's transform actually lives.

WHAT IT MEASURES. Every actor id the capture's `remoteplayer.dynamicslice` instances declare (13 of
them, extracted from the committed replay) is searched for in the client's writable memory. For each
hit it reads a window around the address and looks for a plausible world coordinate pair
(`9000 < x < 9700`, `2500 < y < 3000`). That distinguishes three states:

  * the id is absent          -> the client never created that actor (nothing to move);
  * the id is present, no pair -> the client holds it but not next to a position;
  * the id is present WITH a pair -> an entity object, and the offset is where its transform is.

THE POSITIVE CONTROL IS THE LOCAL PLAYER. Its actor id certainly exists and certainly carries a
position, so a run that reports zero hits for the player is a broken scan (a budget or range
mistake), not a negative result. The probe refuses to report a conclusion without it.

Read-only: no hooks, no writes, no patch. It only reads memory.

NO UNLOAD AT THE END, ON PURPOSE. `frida-agent.dll_unloaded` execute-after-unload is a measured
crash source in this project (offset 0x9c7e0, reproduced again on 2026-10-20 twice from the
launcher's own DTLS patch). A read-only scan installs no hooks, but the agent still has to be
unloaded, so this probe leaves the session attached and the process is ended deliberately
(`python ef.py stop`) once the numbers are in.

Usage:
  python ef.py probe frida-actor-transform            # all 13 captured ids + the player
  python ef.py probe frida-actor-transform --window 1024 --timeout 300
"""

from __future__ import annotations

import argparse
import json
import time

import frida

# MEASURED from the committed replay with `decode_bundle`: every `<remoteplayer.dynamicslice GUID>
# <00 00 00 02> <16-byte actor id>` instance in the type-0x08 bundles, and the record id it belongs
# to. Record 1 is the LOCAL PLAYER (its spawn record, 48 fragments) - the positive control.
CAPTURED = {
    "player(rid 1)": "1a954abc4b3185bfbe37c3d8592618e0",
    "rid 29": "3c757da5b2549230fdd559012f5bb05e",
    "rid 30": "e2917c2cb9fb4ed3f1018cef205f6686",
    "rid 60": "e440562ddc204f7f8cb013ceb696fff4",
    "rid 79": "fe77eefa932f9c7c9d784a8f6f4430ef",
    "rid 87": "5eeaa6572a88a3bee0488cb4dcb9895e",
    "rid 88": "4c48151bfa86ffbb33c823cd6d9c1479",
    "rid 89": "c229bb14a86d25cc50f115381df53b7d",
    "rid 90": "84515ae9909636e95f2d6df3d0440c0e",
    "rid 91": "dcf7ff88ddb9cbf893ffa94f3f130a9d",
    "rid 92": "c0f655ce4e0991da5d38262dee3c5290",
    "rid 93": "9c5c7eb3e469380ea1a41cf482316a35",
    "rid 94": "8e4972fff4e9b510fb6ebae832f27c59",
}

JS = r"""
const PATTERNS = %PATTERNS%;   // [{label, pattern: "aa bb cc .."}]
const WINDOW = %WINDOW%;       // bytes read FORWARD from a hit
const BUDGET = %BUDGET%;   // scanning budget in bytes; see --budget-mb

// Memory.scan is the NATIVE scanner; a hand-written JS byte loop over 13 patterns x 3 GB did not
// finish in 7 minutes (measured 2026-10-20) and produced no result. Scan natively, then read the
// window around each hit.
const ranges = Process.enumerateRanges('rw-')
  .filter(r => r.size >= 4096 && r.size <= 256 * 1024 * 1024);
let used = 0;
const kept = ranges.filter(r => { if (used + r.size > BUDGET) return false; used += r.size; return true; });
send({ ev: 'ranges', count: kept.length, totalMB: Math.round(used / 1048576) });

const hits = {};
for (const p of PATTERNS) hits[p.label] = [];

function worldPairsAround(addr) {
  const out = [];
  try {
    const back = Math.min(WINDOW, 256);
    const buf = addr.sub(back).readByteArray(back + WINDOW);
    if (buf === null) return out;
    const dv = new DataView(buf);
    // BOTH ENDIANNESSES. The WIRE is big-endian, but a native struct holds the same floats
    // little-endian - and the first version of this probe only looked for the big-endian form,
    // which is why every id came back with 0 pairs (measured 2026-10-20).
    for (let o = 0; o + 8 <= buf.byteLength; o += 4) {
      const xb = dv.getFloat32(o, false), yb = dv.getFloat32(o + 4, false);
      if (xb > 9000 && xb < 9700 && yb > 2500 && yb < 3000) {
        out.push({ rel: o - back, order: 'be', x: Math.round(xb * 100) / 100, y: Math.round(yb * 100) / 100 });
        if (out.length >= 6) return out;
      }
      const xl = dv.getFloat32(o, true), yl = dv.getFloat32(o + 4, true);
      if (xl > 9000 && xl < 9700 && yl > 2500 && yl < 3000) {
        out.push({ rel: o - back, order: 'le', x: Math.round(xl * 100) / 100, y: Math.round(yl * 100) / 100 });
        if (out.length >= 6) return out;
      }
    }
  } catch (e) { }
  return out;
}

let ri = 0;
function nextRange() {
  if (ri >= kept.length) {
    const summary = {};
    for (const p of PATTERNS) {
      const h = hits[p.label];
      summary[p.label] = {
        hits: h.length,
        withPair: h.filter(x => x.pairs.length > 0).length,
        samples: h.slice(0, 8),
      };
    }
    send({ ev: 'done', summary: summary });
    return;
  }
  const r = kept[ri++];
  let pi = 0;
  function nextPattern() {
    if (pi >= PATTERNS.length) { setImmediate(nextRange); return; }
    const p = PATTERNS[pi++];
    try {
      Memory.scan(r.base, r.size, p.pattern, {
        onMatch(address, size) {
          if (hits[p.label].length < 500) {
            hits[p.label].push({ at: address.toString(), pairs: worldPairsAround(address) });
          }
        },
        onComplete() { setImmediate(nextPattern); },
        onError(e) { setImmediate(nextPattern); },
      });
    } catch (e) { setImmediate(nextPattern); }
  }
  nextPattern();
}
nextRange();
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=768, help="bytes read around a hit")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--only", default=None,
                    help="scan ONE captured label only (e.g. 'player(rid 1)'). "
                         "The full scan is 13 patterns x ~3 GB, which does not "
                         "finish in 15 minutes on this machine; the positive "
                         "control alone is 1/13 of that and answers whether the "
                         "scan works at all.")
    ap.add_argument("--budget-mb", type=int, default=3000,
                    help="memory budget in MB. Lowering it trades coverage for "
                         "time; the positive control must still be found.")
    args = ap.parse_args()

    selected = CAPTURED
    if args.only:
        selected = {k: v for k, v in CAPTURED.items() if args.only.lower() in k.lower()}
        if not selected:
            print(f"[census] --only {args.only!r} matched none of: "
                  f"{', '.join(CAPTURED)}")
            return 2
    patterns = [
        {"label": label, "pattern": " ".join(f"{b:02x}" for b in bytes.fromhex(actor))}
        for label, actor in selected.items()
    ]
    # The scan cost is patterns x budget, so state both up front: the earlier
    # version reported only the ranges and a 15-minute run looked unexplained.
    print(f"[census] {len(patterns)} pattern(s) x {args.budget_mb} MB budget "
          f"= {len(patterns) * args.budget_mb} MB of scanning", flush=True)
    source = (JS.replace("%PATTERNS%", json.dumps(patterns))
               .replace("%WINDOW%", str(args.window))
               .replace("%BUDGET%", str(args.budget_mb * 1024 * 1024)))

    device = frida.get_local_device()
    pid = next((p.pid for p in device.enumerate_processes()
                if p.name.lower() == "newworld.exe"), None)
    if pid is None:
        print("[census] no NewWorld.exe running")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    done: dict = {}

    def on_message(message, _data):
        if message.get("type") != "send":
            print("[census] err:", str(message.get("description"))[:200], flush=True)
            return
        payload = message["payload"]
        if payload.get("ev") == "ranges":
            print(f"[census] scanning {payload['count']} ranges, {payload['totalMB']} MB", flush=True)
        elif payload.get("ev") == "done":
            done.update(payload["summary"])

    script.on("message", on_message)
    script.load()
    print(f"[census] attached pid={pid}; window={args.window}", flush=True)

    end = time.time() + args.timeout
    while not done and time.time() < end:
        time.sleep(2)

    if not done:
        print("[census] TIMED OUT - no summary; treat as no result, not as a negative")
        return 1

    print("\n%-14s %6s %9s" % ("actor", "hits", "with pair"))
    for label in selected:
        row = done.get(label) or {}
        print("%-14s %6d %9d" % (label, row.get("hits", 0), row.get("withPair", 0)))

    player = done.get("player(rid 1)") or {}
    if not player.get("hits"):
        print("\nPOSITIVE CONTROL FAILED: the local player's actor id was not found. "
              "The scan is broken (budget/ranges), so no conclusion is possible.")
        return 2

    print("\n-- hits carrying a world position (the interesting ones) --")
    for label in selected:
        row = done.get(label) or {}
        for sample in row.get("samples", []):
            if sample.get("pairs"):
                print(f"{label:14s} {sample['at']} {sample['pairs']}")

    out = ".azoth/state/actor-census.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(done, handle, indent=2)
    print(f"\n[census] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
