"""Verify the request->response map in `rep.py` against the captured replay.

WHY THIS EXISTS
===============
The server decides whether to send a captured typed response by asking "did our client send
the request this answers?". That decision is only as good as the request->response map, which
is a hand-checked table (`azoth_world.rep.RESPONSE_REQUESTS`). A table with no verification
drifts: a regenerated name table, a re-cut capture, or a typo in a wire id would silently make
the server suppress a response the client needs, or send one it cannot receive.

This tool re-derives the pairs from the capture itself and reports every disagreement.

THE DERIVATION, AND WHY IT IS NOT "THE NEAREST PRECEDING MESSAGE"
================================================================
The obvious rule - a response follows its request - is too weak on its own. Measured: the
Contracts response at capture seq 67 is preceded at seq 65 by an unrelated
`MountComponentServerFacet_OnMountSlowWalkChanged`, so "nearest preceding" picks the wrong
request. A pair is therefore accepted on EITHER of two independent signals:

  * ORDERING  the request appears in the capture BEFORE the response (any distance);
  * NAMING    request and response are in the same component family
              (`XComponentServerFacet_<M>` / `XComponentClientFacet_<On><M>`).

A response whose request satisfies neither is reported. An EMPTY request tuple in the table
means the response is unsolicited, which is only accepted when the capture really has no
preceding request in that family.

Usage:
    python scripts/request-response-map.py            # report, exit 1 on a contradiction
    python scripts/request-response-map.py --check     # same, quiet on success
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "world" / "src"))

from azoth_world.javelin.replay_store import ReplayStore  # noqa: E402
from azoth_world.rep import RESPONSE_REQUESTS  # noqa: E402

NAMES = ROOT / "research" / "derived" / "wire-type-names.json"
CAPTURE = ROOT / "services" / "world" / "replay" / "messages-redacted.txt"


def _names() -> dict[int, str]:
    if not NAMES.is_file():
        return {}
    data = json.loads(NAMES.read_text(encoding="utf-8"))
    return {r["wire_type"]: r["name"] for r in data["names"] if r.get("name")}


def _family(name: str) -> str | None:
    m = re.match(r"^(.*?)(ServerFacet|ClientFacet)", name)
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="quiet unless something disagrees")
    args = ap.parse_args()

    names = _names()
    messages = ReplayStore(CAPTURE).messages

    # Named ServerFacet requests in the capture, by component family and by position.
    family_requests: dict[str, set[int]] = {}
    for type_id, name in names.items():
        if "ServerFacet_" in name:
            fam = _family(name)
            if fam:
                family_requests.setdefault(fam, set()).add(type_id)

    preceding: set[int] = set()
    responses: list[tuple[int, int, set[int]]] = []  # (seq, type_id, requests seen so far)
    for msg in messages:
        name = names.get(msg.type_id) or ""
        if msg.direction == "W" and "ServerFacet_" in name:
            preceding.add(msg.type_id)
        if msg.direction == "R" and "ClientFacet_" in name:
            responses.append((msg.seq, msg.type_id, set(preceding)))

    mismatches: list[str] = []
    lines: list[str] = []
    seen: set[int] = set()
    for seq, response, before in responses:
        if response in seen:
            continue
        seen.add(response)
        name = names.get(response, "?")
        table = RESPONSE_REQUESTS.get(response)
        fam = _family(name) or ""
        candidates = family_requests.get(fam, set())
        if table is None:
            mismatches.append(
                f"{hex(response)} {name}: captured response has no entry in RESPONSE_REQUESTS"
            )
            continue
        if table:
            if not (set(table) & before) and not (set(table) & candidates):
                mismatches.append(
                    f"{hex(response)} {name}: table requires {[hex(r) for r in table]}, but "
                    f"none appears before it in the capture and none is in family {fam!r}"
                )
            else:
                why = "ordering" if set(table) & before else "naming"
                lines.append(f"  {hex(response):>8} {name:<60} <- {[hex(r) for r in table]} ({why})")
        else:
            if before & candidates:
                mismatches.append(
                    f"{hex(response)} {name}: table says unsolicited, but the capture has a "
                    f"{fam} request before it"
                )
            else:
                lines.append(f"  {hex(response):>8} {name:<60} <- (unsolicited)")

    if not args.check:
        print(f"capture messages: {len(messages)}, ClientFacet responses: {len(seen)}")
        print()
        print("\n".join(lines))
        unverified = sorted(set(RESPONSE_REQUESTS) - seen)
        if unverified:
            # Informational, not a failure: a table entry whose response is unnamed in the
            # capture (e.g. 0x1033 GridTracking, whose name only the client's own RMIDispatch
            # error supplies) cannot be classified here. It must be documented instead.
            print()
            print("in the table but not classifiable from the capture: "
                  + ", ".join(hex(t) for t in unverified))

    if mismatches:
        print()
        print("request-response map CONTRADICTS the capture:")
        for line in mismatches:
            print(f"  - {line}")
        return 1
    if not args.check:
        print()
        print(f"request-response map consistent with the capture ({len(seen)} responses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
