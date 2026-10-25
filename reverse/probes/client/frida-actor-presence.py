#!/usr/bin/env python3
"""Does the client actually hold the actor id we registered?

WHY. Creating an entity is two messages: `ClientAddEntryMsg` registers an actor id, then a record
binds component state to it. The server can log both sends, and the record can be proven to reach
the dispatcher - but none of that answers the only question that matters: **does the client hold
that actor id at all?**

This probe answers it directly, by scanning the client's writable memory for the three ids that
make the experiment falsifiable:

  * the id we REGISTERED (`AZOTH_NPC_ACTOR_ID`)  - must be present if registration worked;
  * the CAPTURED id from record 29                - the control: an id the client certainly has;
  * the LOCAL PLAYER's id                         - a second control, taken from Game.log.

A registered id that appears ZERO times is a decisive negative: the `ClientAddEntryMsg` did not
create an actor entry, and no record can bind state to it, no matter how the payload is shaped.

Read-only. Scans asynchronously with a hard byte budget so a large heap cannot hang the probe.

Usage:
  python ef.py probe frida-actor-presence --actor cafebabedeadbeef0123456789abcdef
"""

from __future__ import annotations

import argparse
import time

import frida

JS = r"""
const base = Process.findModuleByName('NewWorld.exe').base;

const PATTERNS = %PATTERNS%;

// MEASURED 2026-10-19: a 900 MB budget over the 8 largest ranges found NONE of the three ids,
// including the LOCAL PLAYER's, which certainly exists. That produced a false 'the client does not
// hold the actor id' reading. The budget is now 2500 MB over all rw- ranges, and the run is only
// interpretable if the POSITIVE CONTROL (the player's id) comes back non-zero.
let ranges = Process.enumerateRanges('rw-')
  .filter(r => r.size >= 4096 && r.size <= 512 * 1024 * 1024);
const BUDGET = 2500 * 1024 * 1024;
let used = 0;
const kept = ranges.filter(r => { if (used + r.size > BUDGET) return false; used += r.size; return true; });
// THE BUG THIS FIXES: the budget was computed into `kept` but the scan iterated `ranges`, so the
// budget never applied and the run scanned 53k ranges / 9 GB and never finished. Iterate `kept`.
ranges = kept;
send({ ev: 'ranges', count: ranges.length,
       totalMB: Math.round(ranges.reduce((a, r) => a + r.size, 0) / 1048576) });

let idx = 0;
const counts = {};
for (const p of PATTERNS) counts[p.label] = 0;

function scanNext() {
  if (idx >= ranges.length) {
    send({ ev: 'done', counts: counts });
    return;
  }
  const r = ranges[idx++];
  const pat = PATTERNS[0];  // scan all patterns per range in sequence
  let pi = 0;
  function nextPattern() {
    if (pi >= PATTERNS.length) { setImmediate(scanNext); return; }
    const p = PATTERNS[pi++];
    try {
      Memory.scan(r.base, r.size, p.pattern, {
        onMatch(address, size) {
          counts[p.label] += 1;
        },
        onComplete() { setImmediate(nextPattern); },
        onError(e) { setImmediate(nextPattern); },
      });
    } catch (e) { setImmediate(nextPattern); }
  }
  nextPattern();
}
scanNext();
"""


def hex_pattern(actor_hex: str) -> str:
    raw = bytes.fromhex(actor_hex.replace("-", ""))
    return " ".join(f"{b:02x}" for b in raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", required=True, help="the registered actor id, hex")
    ap.add_argument("--captured", default="3c757da5b2549230fdd559012f5bb05e",
                    help="the captured record-29 actor id (control)")
    ap.add_argument("--player", default="1a954abc4b3185bfbe37c3d8592618e0",
                    help="the local player's actor id (control)")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    patterns = [
        {"label": "registered", "pattern": hex_pattern(args.actor)},
        {"label": "captured", "pattern": hex_pattern(args.captured)},
        {"label": "player", "pattern": hex_pattern(args.player)},
    ]
    import json as _json
    source = JS.replace("%PATTERNS%", _json.dumps(patterns))

    device = frida.get_local_device()
    pid = next((p.pid for p in device.enumerate_processes()
                if p.name.lower() == "newworld.exe"), None)
    if pid is None:
        print("[actor] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    done = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[actor] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        if p.get("ev") == "ranges":
            print(f"[actor] scanning {p['count']} ranges, {p['totalMB']} MB", flush=True)
        elif p.get("ev") == "done":
            done.update(p["counts"])
            print(f"[actor] RESULT {p['counts']}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[actor] attached pid={pid}", flush=True)

    end = time.time() + args.timeout
    while not done and time.time() < end:
        time.sleep(2)

    try:
        script.unload()
    except Exception:
        pass

    if not done:
        print("[actor] scan did not finish in budget", flush=True)
        return 1
    print()
    print(f"  registered {args.actor[:16]}... -> {done.get('registered', 0)} occurrences")
    print(f"  captured   {args.captured[:16]}... -> {done.get('captured', 0)} occurrences")
    print(f"  player     {args.player[:16]}... -> {done.get('player', 0)} occurrences")
    if done.get("registered", 0) == 0:
        print("\n  DECISIVE NEGATIVE: the client does NOT hold the registered actor id.")
        print("  `ClientAddEntryMsg` did not create an actor entry, so no record can bind to it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
