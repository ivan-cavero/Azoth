#!/usr/bin/env python3
"""Drive a labelled action sequence against the in-world client and timestamp it.

WHY THIS EXISTS
===============
`field-differential.py` answers "which byte offsets change across a set of bodies". On a
live session most offsets change, because the player is moving continuously -- so the map
says where *something* varies but not what each field MEANS. Naming a field needs one
thing varied at a time.

The measurement this enables: hold one action per segment, then compare the segments.
An offset that is constant WITHIN every segment but differs BETWEEN two segments is
correlated with the action that separates them. An offset that wobbles inside a segment
is noise from continuous motion, whatever it is.

So this script produces the labels, and `field-differential --segments` consumes them.
The two are separate on purpose: recording is timing-sensitive and needs the live client,
while the analysis is offline and repeatable.

WHAT IT DOES NOT DO
===================
It cannot know whether an action had any effect. The client may ignore a key, the window
may lose focus, or the player may be blocked by geometry. A segment where nothing moved
looks identical to a segment where the field never changes, which is why every segment is
recorded with the wall-clock window it covered and the analysis reports a *delta* between
segments rather than an absolute.

Usage:
    python ef.py run capture-segments --plan walk
    python ef.py run capture-segments --out .azoth/tmp/segments.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Windows scan codes, as the repo's gui helpers expect them.
SC_W = 0x11
SC_A = 0x1E
SC_D = 0x20
SC_SPACE = 0x39
SC_Q = 0x10
SC_E = 0x12

# Each entry: (label, what to do, seconds). `hold` holds one scan code; `idle` sends
# nothing; `tap` presses and releases quickly.
PLANS: dict[str, list[tuple[str, str, int]]] = {
    # The first plan. Deliberately interleaves two idle segments so that a field which
    # merely drifts over time is distinguishable from one tied to an action: if a value
    # differs between the two idles, it is not action-correlated.
    "walk": [
        ("idle-before", "idle", 6),
        ("walk-forward", f"hold:{SC_W}", 4),
        ("idle-after-walk", "idle", 5),
        ("strafe-left", f"hold:{SC_A}", 3),
        ("strafe-right", f"hold:{SC_D}", 3),
        ("idle-mid", "idle", 5),
        ("jump", f"tap:{SC_SPACE}", 2),
        ("idle-end", "idle", 6),
    ],
}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gui(script: str, *args: str) -> int:
    """Run a scripts/gui helper. These are the measured toolchain, not generic automation."""
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gui" / script), *args],
        cwd=REPO,
        check=False,
    ).returncode


def run_action(kind: str, seconds: int) -> str | None:
    """Perform one action and return a note about whether it appeared to work."""
    if kind == "idle":
        time.sleep(seconds)
        return None
    verb, _, value = kind.partition(":")
    scan = int(value, 0)
    if verb == "hold":
        code = gui("hold-key.py", "New World", hex(scan), str(float(seconds)))
        return None if code == 0 else f"hold-key exited {code}"
    if verb == "tap":
        code = gui("hold-key.py", "New World", hex(scan), "0.12")
        time.sleep(max(0.0, seconds - 0.12))
        return None if code == 0 else f"hold-key exited {code}"
    raise SystemExit(f"unknown action kind: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default="walk", choices=sorted(PLANS))
    parser.add_argument("--out", default="segments.json")
    parser.add_argument("--corpus", default=".azoth/logs/world.log",
                        help="world log being written; only used to record its byte size "
                             "at the start so the analysis can read the new tail")
    args = parser.parse_args()

    plan = PLANS[args.plan]
    corpus = REPO / args.corpus
    if not corpus.is_file():
        raise SystemExit(f"corpus not found: {corpus}")
    start_offset = corpus.stat().st_size

    segments = []
    print(f"plan {args.plan}: {len(plan)} segments, corpus offset {start_offset}")
    for label, kind, seconds in plan:
        started = now_utc()
        print(f"  [{started}] {label:18} {kind:16} {seconds}s")
        note = run_action(kind, seconds)
        finished = now_utc()
        entry = {"label": label, "action": kind, "seconds": seconds,
                 "start": started, "end": finished}
        if note:
            entry["note"] = note
            print(f"       note: {note}")
        segments.append(entry)

    payload = {
        "plan": args.plan,
        "corpus": str(corpus),
        "corpus_offset_at_start": start_offset,
        "recorded_at": now_utc(),
        "segments": segments,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    print("next: python ef.py re field-differential --type 0x635 "
          f"--corpus {args.corpus} --length <N> --segments {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
