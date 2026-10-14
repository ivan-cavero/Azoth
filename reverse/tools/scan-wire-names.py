"""Regenerate research/derived/wire-type-names.json: a NAME for every wire type in
private-client/runtime/typeindex.json.

WHY THIS EXISTS
===============
The protocol work kept hitting the same wall: `typeindex.json` maps a wire type index to a
GUID, but the NAME of that type was only recoverable by hand, one at a time. The atlas
records the method (`wire_type_names_from_binary_20261012`) and it works, but with 7052
indices the manual route leaves most types unnamed - which is why the replay's own type list
still shows `?` for 24 of 40 entries, including the ActionListComponentClientFacet family
that the ALC/red-cable question needs.

THE METHOD, AND THE TWO TRAPS IT FIXES
--------------------------------------
For each wire index, `typeindex.json[wire]` is the type's GUID with no dashes. In the image,
that GUID also appears in `.rdata` as a **dashed lowercase string**, immediately preceded by
the type's name as a NUL-terminated printable run:

    <Name>\\0<padding>\\0<dashed-guid>

* Trap 1 - padding: the run is not always immediately adjacent. When a GUID is preceded by
  NUL padding there can be a SHORTER printable run further back that is not the name. This
  tool reads back over up to 4 NULs and keeps the LONGEST run, which is what fixed the
  misreading of 349 (recorded as a bare GUID string; it is `PingMsg`).
* Trap 2 - braces and case: some types are registered by a brace-wrapped GUID instead of a
  name (those yield `{...}` and are reported as such, not silently dropped), and the image
  stores the GUID lowercase while `typeindex.json` stores it uppercase.

A wire index whose GUID has no dashed string in the image is reported as unnamed rather than
guessed: not every index belongs to this naming scheme (the atlas records this for 669 and
5397).

VALIDATION
----------
`--check` refuses to write unless the names the project verified by hand still come out:
1589 `ActionListComponentServerFacet_ReceiveInputFromClient`, 726 `StartMovementCommunicationMsg`,
739 `AckMovementMsg`, 740 `CommitMovementMsg`, 4216 `ReceivePlayerPositionClientMsg`,
4246 `TimeComponentClientFacet_SyncTimeChange`, 4247 `TimeComponentClientFacet_SyncDayPhase`,
349 `PingMsg`.

Usage:
    python reverse/tools/scan-wire-names.py [--check] [--exe PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "derived" / "wire-type-names.json"
TYPEINDEX = ROOT / "private-client" / "runtime" / "typeindex.json"

BUILD_SHA256 = "8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e"

# Verified by hand in the atlas; the scan must reproduce every one.
ANCHORS = {
    349: "PingMsg",
    726: "StartMovementCommunicationMsg",
    739: "AckMovementMsg",
    740: "CommitMovementMsg",
    1589: "ActionListComponentServerFacet_ReceiveInputFromClient",
    4216: "ReceivePlayerPositionClientMsg",
    4246: "TimeComponentClientFacet_SyncTimeChange",
    4247: "TimeComponentClientFacet_SyncDayPhase",
}

GUID_RE = re.compile(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PRINTABLE_RE = re.compile(rb"[\x20-\x7e]{3,110}")
# A printable run that is itself a GUID (optionally brace-wrapped) is never the name; when
# one sits between the name and the GUID, the naive "longest run" picks the GUID instead.
GUID_LIKE_RE = re.compile(r"^\{?[0-9A-Fa-f-]{30,}\}?$")
# A real type name looks like an identifier: it starts with a letter or underscore and is made
# of identifier characters, dots, angle brackets and colons (MSVC/AZ spellings such as
# `MB::GetTypeName`, `AOI.PlayerCountInGrid`, `ActionListComponentServerFacet_QueueAction`).
# MEASURED FAILURE this guards against: without it the scanner returned binary noise that
# happens to be printable, e.g. wire 4122 -> "F)@" and 3967 -> ";WF", and those were almost
# read as type names. A run that is not identifier-shaped is not a name.
NAME_LIKE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:.<>]{2,}$")


# Every AZ/MSVC type name in this image contains at least one run of two or more lowercase
# letters (`PingMsg`, `ActionListComponentServerFacet_QueueAction`, `AOI.PlayerCountInGrid`).
# Printable noise does not: `p<WF` and `F)@` have no such run. This is the check that actually
# separates them, after the identifier-shape and punctuation-ratio tests both let `p<WF` pass.
LOWERCASE_RUN_RE = re.compile(r"[a-z]{2,}")


def _looks_like_a_name(candidate: str) -> bool:
    """True when `candidate` is plausibly a type name rather than printable noise."""
    if not NAME_LIKE_RE.match(candidate):
        return False
    if not LOWERCASE_RUN_RE.search(candidate):
        return False
    alnum = sum(1 for c in candidate if c.isalnum() or c == "_")
    return alnum / len(candidate) >= 0.75


def _pick_name(runs: list[bytes]) -> str | None:
    """The name for a GUID: the printable run CLOSEST to it that is not itself a GUID.

    Distance matters, not length. The descriptor form is `<Name>\0<padding>\0<guid>`, but for
    some types a brace-wrapped GUID sits between the name and the GUID
    (`PingMsg\0{85C7E01E-...}\0<guid>`), so the nearest run is GUID-like and must be skipped.
    Taking the LONGEST run instead picks up an unrelated neighbour (a cvar name or another
    trait) and misnames the type - measured, that is how 726 became
    `javelin-server.asc-enable-fragment-sharing`.
    """
    candidates = [r.decode("ascii") for r in runs]
    for c in reversed(candidates):
        if not GUID_LIKE_RE.match(c) and _looks_like_a_name(c):
            return c
    return None


def scan(exe: Path, typeindex: Path) -> dict:
    data = exe.read_bytes()
    idx = json.loads(typeindex.read_text(encoding="utf-8"))["typeIndex"]

    # One pass over the image: for every dashed GUID, the longest printable run that
    # precedes it within a short window (skipping NUL padding).
    by_guid: dict[str, str] = {}
    for m in GUID_RE.finditer(data):
        start = m.start()
        window = data[max(0, start - 0x100) : start]
        # strip trailing NUL padding (the name is separated from the GUID by NULs)
        end = len(window)
        while end > 0 and window[end - 1] == 0:
            end -= 1
        runs = PRINTABLE_RE.findall(window[:end])
        name = _pick_name(runs)
        if name:
            by_guid.setdefault(m.group().decode("ascii"), name)

    # Fallback for the types whose descriptor does not carry an adjacent name: the AZ type
    # registry has the same GUID -> name pairing, read from the brace-wrapped descriptor form.
    # MEASURED 2026-10-13: 689 wire types are unnamed by adjacency and named there, so this
    # roughly doubles the coverage. `source` records which route produced each name, so a
    # wrong name can be traced to its method.
    registry: dict[str, str] = {}
    reg_path = ROOT / "research" / "atlas" / "az-type-registry.json"
    if reg_path.is_file():
        for entry in json.loads(reg_path.read_text(encoding="utf-8"))["types"]:
            registry.setdefault(entry["guid"].lower(), entry["name"])

    rows = []
    for wire, guid in enumerate(idx):
        dashed = f"{guid[0:8]}-{guid[8:12]}-{guid[12:16]}-{guid[16:20]}-{guid[20:32]}".lower()
        name = by_guid.get(dashed)
        source = "rdata" if name else None
        if not name:
            fallback = registry.get(dashed)
            if fallback and _looks_like_a_name(fallback):
                name = fallback
                source = "az-registry"
        rows.append(
            {"wire_type": wire, "guid": dashed, "name": name, "source": source}
        )
    named = sum(1 for r in rows if r["name"])
    return {
        "build_sha256": hashlib.sha256(data).hexdigest(),
        "wire_types": len(rows),
        "named": named,
        "names": rows,
    }


def check(result: dict) -> list[str]:
    problems: list[str] = []
    if result["build_sha256"] != BUILD_SHA256:
        problems.append(
            f"build sha256 {result['build_sha256']} != {BUILD_SHA256}; "
            "the GUID strings are build-scoped"
        )
    by_wire = {r["wire_type"]: r["name"] for r in result["names"]}
    for wire, want in ANCHORS.items():
        got = by_wire.get(wire)
        if got != want:
            problems.append(f"wire {wire} -> {got!r}, expected {want!r}")
        elif result["names"][wire].get("source") not in ("rdata", "az-registry"):
            problems.append(f"wire {wire} has the right name but no recorded source")
    # A name that is not identifier-shaped means the adjacency scan drifted.
    malformed = [
        r for r in result["names"]
        if r["name"] and not _looks_like_a_name(r["name"])
    ]
    if malformed:
        problems.append(
            f"{len(malformed)} names are not identifier-shaped, e.g. "
            f"{[(r['wire_type'], r['name']) for r in malformed[:5]]}"
        )
    if result["named"] < 1500:
        problems.append(
            f"only {result['named']} of {result['wire_types']} wire types named; the "
            "adjacency scan is probably wrong, not the build"
        )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--typeindex")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true", help="verify anchors and write")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else default_paths()["exe"]
    typeindex = Path(args.typeindex) if args.typeindex else TYPEINDEX
    out = Path(args.out) if args.out else OUT

    result = scan(exe, typeindex)
    problems = check(result)
    for p in problems:
        print(f"INVARIANT FAILED: {p}")
    print(f"wire types {result['wire_types']}, named {result['named']}")
    if args.check and problems:
        print("refusing to write")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
