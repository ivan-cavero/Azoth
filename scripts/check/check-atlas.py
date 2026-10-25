#!/usr/bin/env python3
"""Validate every atlas ontology concept against its schema.

WHY THIS EXISTS
===============
`research/atlas/ontology/schema.json` is the contract for concept files, and it
sets `additionalProperties: false`. Nothing enforced it, so a hand-written field
that the schema does not allow could sit in a concept file indefinitely: the
files stayed valid JSON and every reader ignored the extra key. MEASURED
2026-10-25: two such keys had been introduced in one session alone — a `struct`
block on the level-info concept and an `open_questions` list on the
self-identification concept — and neither would ever have been noticed.

This checker is deliberately the schema's own rules, not a second opinion: it
reads `required` and `properties` from the schema file, so widening the schema
widens the check automatically.

It does not implement JSON Schema. It enforces the two rules that actually caught
real mistakes: every required key is present, and no key outside `properties`
appears. Deeper validation (enums, patterns, nesting) would need a dependency the
lab does not pin.

Usage:
    python scripts/check/check-atlas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "research" / "atlas" / "ontology"
SCHEMA = ONTOLOGY / "schema.json"
CONCEPTS = ONTOLOGY / "concepts"


def fail(msg: str) -> None:
    print(f"check-atlas: FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{path.relative_to(ROOT)}: {exc}")


def main() -> int:
    if not SCHEMA.is_file():
        fail("research/atlas/ontology/schema.json is missing")
    if not CONCEPTS.is_dir():
        fail("research/atlas/ontology/concepts/ is missing")

    schema = load(SCHEMA)
    required = list(schema.get("required") or [])
    allowed = set(schema.get("properties") or {})
    if not required or not allowed:
        fail("schema.json declares no required keys or no properties")

    files = sorted(CONCEPTS.glob("*.json"))
    if not files:
        fail("no concept files found")

    problems: list[str] = []
    seen_uids: dict[str, str] = {}
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        concept = load(path)
        if not isinstance(concept, dict):
            problems.append(f"{rel}: not a JSON object")
            continue
        for key in required:
            if key not in concept:
                problems.append(f"{rel}: missing required key {key!r}")
        for key in sorted(set(concept) - allowed):
            problems.append(f"{rel}: key {key!r} is not allowed by schema.json")
        uid = concept.get("uid")
        if isinstance(uid, str):
            if uid in seen_uids:
                problems.append(f"{rel}: uid {uid!r} already used by {seen_uids[uid]}")
            else:
                seen_uids[uid] = rel
        evidence = concept.get("evidence")
        if isinstance(evidence, list):
            for i, item in enumerate(evidence):
                if not isinstance(item, dict):
                    problems.append(f"{rel}: evidence[{i}] is not an object")
                    continue
                extra = set(item) - {"type", "ref"}
                if extra:
                    problems.append(
                        f"{rel}: evidence[{i}] has keys outside type/ref: {sorted(extra)}"
                    )
                for key in ("type", "ref"):
                    if key not in item:
                        problems.append(f"{rel}: evidence[{i}] is missing {key!r}")

    problems.extend(index_problems(seen_uids))

    if problems:
        for p in problems:
            print(f"check-atlas: FAIL: {p}", file=sys.stderr)
        raise SystemExit(1)

    print(f"check-atlas: ok ({len(files)} concepts, {len(required)} required keys)")
    return 0


def index_problems(by_file: dict[str, str]) -> list[str]:
    """The three indexes must agree with the concept files, in both directions.

    MEASURED 2026-10-25: adding a concept without touching `by-uid`/`by-kind`/`by-wire`
    leaves the map quietly incomplete, and the reverse (an index entry pointing at a
    concept that was renamed or deleted) leaves a dangling reference nobody notices.
    """
    problems: list[str] = []
    indexes = ONTOLOGY / "indexes"

    by_uid_path = indexes / "by-uid.json"
    if by_uid_path.is_file():
        listed = set(load(by_uid_path).get("uids") or [])
        for uid in sorted(set(by_file) - listed):
            problems.append(f"indexes/by-uid.json is missing {uid!r}")
        for uid in sorted(listed - set(by_file)):
            problems.append(f"indexes/by-uid.json lists {uid!r} but no concept file has it")

    by_kind_path = indexes / "by-kind.json"
    if by_kind_path.is_file():
        kinds = load(by_kind_path).get("kinds") or {}
        for kind, uids in kinds.items():
            for uid in uids:
                if uid not in by_file:
                    problems.append(
                        f"indexes/by-kind.json puts {uid!r} under {kind!r} but no concept file has it"
                    )
        placed = {uid for uids in kinds.values() for uid in uids}
        for uid in sorted(set(by_file) - placed):
            problems.append(f"indexes/by-kind.json does not place {uid!r} under any kind")

    by_wire_path = indexes / "by-wire.json"
    if by_wire_path.is_file():
        wires = load(by_wire_path).get("wires") or {}
        for wire, uid in wires.items():
            if uid not in by_file:
                problems.append(
                    f"indexes/by-wire.json maps wire {wire!r} to {uid!r} but no concept file has it"
                )
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
