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
SC_TAB = 0x0F
SC_I = 0x17
SC_K = 0x25
SC_R = 0x13
SC_F = 0x21
SC_C = 0x2E
SC_1 = 0x02
SC_3 = 0x04
SC_TILDE = 0x29
SC_COMMA = 0x33
SC_LSHIFT = 0x2A
SC_NUMPAD1 = 0x4F
SC_NUMPAD2 = 0x50
SC_M = 0x32
SC_J = 0x24
SC_O = 0x18
SC_P = 0x19
SC_I = 0x17
SC_L = 0x26
SC_N = 0x31
SC_U = 0x16
SC_Y = 0x15
SC_B = 0x30
SC_X = 0x2D
SC_G = 0x22
SC_F3 = 0x3D
SC_F4 = 0x3E
SC_F6 = 0x40
SC_F9 = 0x43
SC_F11 = 0x57

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
    # The in-world UI surfaces: every key here is the one the client's own profile binds
    # (`research/derived/input-contract.json`), so a segment that produces no traffic is a
    # finding about the game, not about the harness having pressed the wrong key.
    #
    # Shape of the plan, and why it is shaped this way:
    #   * two idle baselines at each end, so a type that merely drifts over time is not
    #     mistaken for an action-correlated one;
    #   * "open" and "open-idle" are separate segments: the open request and the panel's
    #     own periodic refresh are different messages, and merging them hides both;
    #   * each surface is opened AND closed, so `appeared` and `vanished` both have a
    #     window to fire in;
    #   * keys 1-9 are pressed twice with different context (once bare, once with the
    #     dialogue window open), because the same key serves a dialogue option and a
    #     consumable quickslot and the traffic is what tells them apart.
    "interact": [
        ("idle-before", "idle", 6),
        ("inventory-open", f"tap:{SC_TAB}", 3),
        ("inventory-open-idle", "idle", 5),
        ("inventory-close", f"tap:{SC_TAB}", 3),
        ("idle-after-inventory", "idle", 4),
        ("skills-open", f"tap:{SC_K}", 3),
        ("skills-open-idle", "idle", 5),
        ("skills-close", f"tap:{SC_K}", 3),
        ("idle-mid", "idle", 4),
        ("sheathe", f"hold:{SC_TILDE}", 3),
        ("draw", f"hold:{SC_TILDE}", 3),
        ("idle-before-abilities", "idle", 4),
        ("ability-1", f"tap:{SC_Q}", 3),
        ("ability-2", f"tap:{SC_R}", 3),
        ("ability-3", f"tap:{SC_F}", 3),
        ("dodge", f"tap:{SC_LSHIFT}", 3),
        ("idle-after-abilities", "idle", 4),
        ("loadout-1", f"tap:{SC_NUMPAD1}", 3),
        ("loadout-2", f"tap:{SC_NUMPAD2}", 3),
        ("idle-after-loadout", "idle", 4),
        ("consumable-3", f"tap:{SC_3}", 3),
        ("interact", f"tap:{SC_E}", 3),
        ("interact-idle", "idle", 5),
        ("dialogue-option-1", f"tap:{SC_1}", 3),
        ("idle-end", "idle", 6),
    ],
    # The surfaces that cannot be driven by a key alone: an NPC conversation that is not
    # where the character stands, the crafting bench, the trading post, and the auction
    # house all need a mouse on a coordinate that expires. This plan therefore does nothing
    # but mark windows, and the operator drives the client during them. It exists so the
    # analysis can be run over mouse work with the same instrument instead of a second,
    # differently shaped one.
    "ui-manual": [
        ("idle-before", "idle", 5),
        ("manual-npc-interact", "idle", 12),
        ("manual-dialogue-open", "idle", 10),
        ("manual-dialogue-choose", "idle", 10),
        ("idle-mid", "idle", 5),
        ("manual-inventory-click-equip", "idle", 12),
        ("manual-inventory-unequip", "idle", 12),
        ("idle-mid-2", "idle", 5),
        ("manual-craft-open", "idle", 12),
        ("manual-craft-make", "idle", 12),
        ("idle-mid-3", "idle", 5),
        ("manual-trading-post-open", "idle", 12),
        ("manual-trading-post-buy", "idle", 12),
        ("idle-end", "idle", 5),
    ],
    # The panels whose content is NOT local. The inventory renders from state the replay
    # already gave it, which is why it sent nothing; these panels cannot render without
    # asking the server, so they are the ones that should produce requests. Each is opened
    # AND closed so the request and the dismiss land in separate windows.
    "panels": [
        ("idle-before", "idle", 5),
        ("map-open", f"tap:{SC_M}", 4),
        ("map-close", f"tap:{SC_M}", 3),
        ("journal-open", f"tap:{SC_J}", 4),
        ("journal-close", f"tap:{SC_J}", 3),
        ("social-open", f"tap:{SC_O}", 4),
        ("social-close", f"tap:{SC_O}", 3),
        ("guild-open", f"tap:{SC_F4}", 4),
        ("guild-close", f"tap:{SC_F4}", 3),
        ("seasons-open", f"tap:{SC_F9}", 4),
        ("seasons-close", f"tap:{SC_F9}", 3),
        ("token-open", f"tap:{SC_F11}", 4),
        ("token-close", f"tap:{SC_F11}", 3),
        ("warboard-open", f"tap:{SC_N}", 4),
        ("warboard-close", f"tap:{SC_N}", 3),
        ("raid-open", f"tap:{SC_L}", 4),
        ("raid-close", f"tap:{SC_L}", 3),
        ("emote-open", f"tap:{SC_P}", 4),
        ("emote-close", f"tap:{SC_P}", 3),
        ("equipset-open", f"tap:{SC_COMMA}", 4),
        ("equipset-close", f"tap:{SC_COMMA}", 3),
        ("idle-after", "idle", 6),
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
