#!/usr/bin/env python3
"""Rebuild the three atlas indexes from the concept files, or check they match.

WHY THIS EXISTS
===============
`indexes/by-uid.json`, `by-kind.json` and `by-wire.json` are hand-maintained.
`scripts/check/check-atlas.py` verifies the concepts and then walks the indexes,
but it only detects drift in ONE direction per index: a uid listed with no
concept file is a dangling reference, and it reports that; a concept file that
the index never lists is reported too, but only for `by-uid` and `by-kind`.
`by-wire` is checked only for dangling entries, so a new wire id can be absent
from it forever without any gate noticing.

MEASURED 2026-11-10: that is exactly what happened. The atlas grew from 82 to
103 cards in the 2026-11-09 campaign and the indexes were never touched:
21 uids missing from `by-uid`, 21 missing from `by-kind` (message 40 on disk
vs 20 indexed, codec 39 vs 38), 23 wire ids missing from `by-wire` and 2 stale.
CI had been red since 2026-10-25, so nothing surfaced it. Updating three JSON
maps by hand on every promotion is a step that will be skipped again; this
script derives them from the concept files so it cannot drift.

Usage:
    python scripts/check/index-atlas.py            # rewrite all three
    python scripts/check/index-atlas.py --check    # exit 1 if they differ
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "research" / "atlas" / "ontology"
CONCEPTS = ONTOLOGY / "concepts"
INDEXES = ONTOLOGY / "indexes"

# The wire id key is a string in every index today. Cards carry it either as a
# hex string ("0x16a0") or as a decimal integer, and one flow uses a symbolic
# id ("carrier-cmd-1"), so the index keeps the card's own spelling rather than
# normalising it: a reader comparing "663" against "0x297" would be wrong, and
# the existing entries are already mixed.
GENERATED_NOTE = "derived-by scripts/check/index-atlas.py"


def load_concepts() -> dict[str, dict]:
    cards: dict[str, dict] = {}
    for path in sorted(CONCEPTS.glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        uid = card.get("uid")
        if not isinstance(uid, str) or not uid:
            raise SystemExit(f"index-atlas: {path.name} has no uid")
        if uid in cards:
            raise SystemExit(f"index-atlas: uid {uid!r} appears twice ({path.name})")
        cards[uid] = card
    if not cards:
        raise SystemExit("index-atlas: no concept files")
    return cards


def build(cards: dict[str, dict]) -> dict[str, dict]:
    by_uid = {"generated": GENERATED_NOTE, "uids": sorted(cards)}
    kinds: dict[str, list[str]] = {}
    for uid, card in cards.items():
        kind = card.get("kind")
        if not isinstance(kind, str) or not kind:
            raise SystemExit(f"index-atlas: {uid} has no kind")
        kinds.setdefault(kind, []).append(uid)
    by_kind = {
        "generated": GENERATED_NOTE,
        "kinds": {kind: sorted(uids) for kind, uids in sorted(kinds.items())},
    }
    wires: dict[str, str] = {}
    for uid, card in cards.items():
        wire = card.get("wire") or {}
        wire_id = wire.get("id") if isinstance(wire, dict) else None
        if wire_id is None:
            continue
        key = str(wire_id)
        if key in wires:
            raise SystemExit(
                f"index-atlas: wire {key} is claimed by both {wires[key]} and {uid}"
            )
        wires[key] = uid
    by_wire = {"generated": GENERATED_NOTE, "wires": dict(sorted(wires.items()))}
    return {"by-uid.json": by_uid, "by-kind.json": by_kind, "by-wire.json": by_wire}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of rewriting the indexes",
    )
    args = ap.parse_args()

    cards = load_concepts()
    wanted = build(cards)
    drifted: list[str] = []
    for name, content in wanted.items():
        path = INDEXES / name
        text = json.dumps(content, indent=1, ensure_ascii=False) + "\n"
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if json.loads(current or "{}") != content:
            drifted.append(name)
            if not args.check:
                INDEXES.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

    if args.check:
        if drifted:
            for name in drifted:
                print(f"index-atlas: {name} is out of date with the concept files")
            print("  run `python scripts/check/index-atlas.py` to regenerate")
            return 1
        print(f"index-atlas: ok ({len(cards)} concepts, 3 indexes)")
        return 0

    for name in drifted:
        print(f"index-atlas: rewrote {name}")
    if not drifted:
        print(f"index-atlas: ok ({len(cards)} concepts, 3 indexes already current)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
