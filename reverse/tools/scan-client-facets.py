"""Regenerate research/derived/client-facet-factories.json: every client facet the
client can construct by name, and the function that constructs it.

WHY THIS EXISTS
===============
The open movement blocker is "the client-side facets for the local player are not
created" (`position_facets_absent_on_the_live_entity_20261012`). Answering it needs
the mechanism that creates a component's client facet, not another message guess.

That mechanism is a **by-name factory per class**, registered in a descriptor table
in `.rdata`. A factory is small and always shaped the same way:

    lVar = <global reflection registry>.CreateByName(<class name>, <size>, <align>, ...);
    <owner> + 0x80 = <ctor>(lVar);          // the facet slot on the owner
    <facet> + 8    = <owner>;               // back pointer

The registry is the global at `0x14a313ff8` -- the same object that backs the
`IPositionReceiver` register-by-name (`FUN_143f98300`) and installer
(`FUN_143f983d0`). So "what creates the ClientFacet" and "what creates the
IPositionReceiver" are the same question about the same registry.

THE TABLE SIGNATURE
-------------------
Each class owns a table whose tail is

    [0x1406c7b30][0x1416a1340][FACTORY][0x14171a8b0][0x1417aae90]

with `FACTORY` in `.text` and unique per class. Scanning for that tail reproduces
every client facet in the build. The class NAME is then recovered without Ghidra:
disassemble the factory and read the rip-relative string operand it passes as the
`CreateByName` name argument.

VALIDATION
----------
`--check` refuses to write unless all of these still hold on the target build:

* every resolved name ends in `ClientFacet` (the table family is exactly the
  client facets, so a stray name means the signature drifted);
* 368 distinct names over 369 tables, with `GameRigidBodyComponentClientFacet`
  the only duplicate;* the three position facets resolve to the VAs they were first measured at.

A name that stops resolving is a hard failure, not a silently dropped row: the
previous version of the component registry in this repo went wrong exactly by
degrading quietly.

Usage:
    python reverse/tools/scan-client-facets.py [--exe PATH] [--check] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "derived" / "client-facet-factories.json"

BUILD_SHA256 = "8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e"

# The five-word table tail. Slot 2 is the per-class factory.
TAIL = (0x1406C7B30, 0x1416A1340, None, 0x14171A8B0, 0x1417AAE90)

# Independently established anchors: class -> factory VAs measured by hand from the
# decompiled factory body (`CreateByName` name argument). A name may legitimately
# own more than one table (`GameRigidBodyComponentClientFacet` owns two).
ANCHORS: dict[str, tuple[int, ...]] = {
    "PlayerPositionTrackingComponentClientFacet": (0x142CFF160,),
    "PositionInTheWorldComponentClientFacet": (0x145C209F0,),
    "PositionalTicketingComponentClientFacet": (0x142605970,),
    "GameRigidBodyComponentClientFacet": (0x141698EA0, 0x141698EB0),
}

EXPECTED_DISTINCT = 368
EXPECTED_TABLES = 369


def _sections(pe: PE) -> tuple[int, int] | None:
    """(start, end) of the section holding the first anchor factory."""
    probe = ANCHORS["PlayerPositionTrackingComponentClientFacet"][0]
    for s in pe.sections:
        if s["va"] <= probe < s["va"] + s["rsize"]:
            return s["va"], s["va"] + s["rsize"]
    return None


def _va_of(pe: PE, foff: int) -> int | None:
    for s in pe.sections:
        if s["raw"] <= foff < s["raw"] + s["rsize"]:
            return s["va"] + (foff - s["raw"])
    return None


def _cstring(pe: PE, va: int, limit: int = 160) -> str | None:
    raw = pe.read_va(va, limit)
    if not raw:
        return None
    end = raw.find(b"\0")
    if end < 0:
        return None
    body = raw[:end]
    if not 6 <= len(body) <= 110:
        return None
    if not all(0x20 <= c < 0x7F for c in body):
        return None
    return body.decode("ascii")


def find_tables(pe: PE, text: tuple[int, int]) -> list[tuple[int, int]]:
    """(table_va, factory_va) for every class whose table tail matches."""
    lo, hi = text
    prefix = struct.pack("<QQ", TAIL[0], TAIL[1])
    after_factory = struct.pack("<Q", TAIL[3])
    tail_end = struct.pack("<Q", TAIL[4])
    out: list[tuple[int, int]] = []
    start = 0
    while True:
        i = pe.data.find(prefix, start)
        if i < 0:
            break
        start = i + 1
        factory = struct.unpack_from("<Q", pe.data, i + 16)[0]
        if not lo <= factory < hi:
            continue
        if pe.data[i + 24 : i + 32] != after_factory:
            continue
        if pe.data[i + 32 : i + 40] != tail_end:
            continue
        table_va = _va_of(pe, i)
        if table_va is None:
            continue
        out.append((table_va, factory))
    return out


def _rip_targets(code: bytes, base: int):
    """Yield the rip-relative memory targets of `lea`/`mov` in a code window."""
    import capstone

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    for insn in md.disasm(code, base):
        if insn.mnemonic not in ("lea", "mov"):
            continue
        for m in re.finditer(r"\[rip \+ (0x[0-9a-f]+)\]", insn.op_str):
            yield insn.address + insn.size + int(m.group(1), 16)


def resolve_name(pe: PE, factory: int) -> str | None:
    """The class name the factory passes to the reflection registry."""
    code = pe.read_va(factory, 0x500)
    if not code:
        return None
    seen: list[str] = []
    for target in _rip_targets(code, factory):
        s = _cstring(pe, target)
        if s:
            seen.append(s)
    for s in seen:
        if s.endswith("ClientFacet"):
            return s
    return seen[0] if seen else None


def scan(exe: Path) -> dict:
    pe = PE(exe)
    text = _sections(pe)
    if text is None:
        raise SystemExit("could not locate the .text section")
    tables = find_tables(pe, text)
    rows = []
    for table_va, factory in tables:
        rows.append(
            {
                "table": f"0x{table_va:x}",
                "factory": f"0x{factory:x}",
                "name": resolve_name(pe, factory),
            }
        )
    rows.sort(key=lambda r: r["factory"])
    return {"build_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "facets": rows}


def check(result: dict) -> list[str]:
    """Return the list of failed invariants (empty means the scan is trustworthy)."""
    problems: list[str] = []
    rows = result["facets"]
    if result["build_sha256"] != BUILD_SHA256:
        problems.append(
            f"build sha256 {result['build_sha256']} != {BUILD_SHA256}; "
            "the table signature is build-scoped"
        )
    unnamed = [r["table"] for r in rows if not r["name"]]
    if unnamed:
        problems.append(f"{len(unnamed)} factories resolved no name: {unnamed[:5]}")
    off_family = sorted({r["name"] for r in rows if r["name"] and not r["name"].endswith("ClientFacet")})
    if off_family:
        problems.append(f"names outside the client-facet family: {off_family[:5]}")
    if len(rows) != EXPECTED_TABLES:
        problems.append(f"{len(rows)} tables, expected {EXPECTED_TABLES}")
    distinct = {r["name"] for r in rows}
    if len(distinct) != EXPECTED_DISTINCT:
        problems.append(f"{len(distinct)} distinct names, expected {EXPECTED_DISTINCT}")
    for name, vas in ANCHORS.items():
        got = sorted(r["factory"] for r in rows if r["name"] == name)
        want = sorted(f"0x{va:x}" for va in vas)
        if got != want:
            problems.append(f"{name} -> {got}, expected {want}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true", help="verify invariants and write")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else default_paths()["exe"]
    out = Path(args.out) if args.out else OUT
    result = scan(exe)
    problems = check(result)
    for p in problems:
        print(f"INVARIANT FAILED: {p}")
    named = sum(1 for r in result["facets"] if r["name"])
    print(f"tables={len(result['facets'])} named={named}")
    if args.check and problems:
        print("refusing to write")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
