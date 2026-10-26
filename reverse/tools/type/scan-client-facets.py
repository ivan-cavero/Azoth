"""Regenerate research/derived/client-facet-factories.json: every client facet the
client can construct by name, and the function that constructs it.

WHY THIS EXISTS
===============
The open movement blocker is "the client-side facets for the local player are not
created" (`position_facets_absent_on_the_live_entity_20261012`). Answering it needs
the mechanism that creates a component's client facet, not another message guess.

That mechanism is a **by-name factory per class**, registered in a descriptor table
in `.rdata`. A factory is small and always shaped the same way. Measured on 1.460,
factory `0x141699ac0` for `GameRigidBodyComponentClientFacet`:

    48 8b 05 .. b7 c7 08            mov  rax,[rip+..]     ; global reflection registry 0x14a315278
    48 8d 48 30                     lea  rcx,[rax+0x30]   ; its registration interface
    48 8b 01                        mov  rax,[rcx]        ; interface vtable
    89 7c 24 38 / 89 7c 24 30 / 48 89 7c 24 28  ; args 2..4 = 0 (edi was zeroed by `33 ff`)
    48 8d 15 e1 46 9a 06            lea  rdx,[rip+..]     ; class name string 0x14803e250
    48 89 54 24 20                  mov  [rsp+20],rdx     ; arg 1 (stack) = name
    45 33 c9                        xor  r9d,r9d
    ba 90 01 00 00 / 41 b8 08 00 00 00  ; size 0x190, align 8
    ff 50 08                        call qword ptr [rax+8] ; CreateByName(...)
    ...
    48 89 ad 80 00 00 00            mov  [rbp+0x80],rdi    ; owner + 0x80 = the new facet
    48 89 6f 08                     mov  [rdi+8],rbp       ; facet + 8    = back pointer

The registry is the same object that backs the `IPositionReceiver` register-by-name
(`FUN_143f98300`) and installer (`FUN_143f983d0`), so "what creates the
ClientFacet" and "what creates the IPositionReceiver" are the same question about
the same registry.

THE TABLE SIGNATURE
-------------------
Each class owns a table whose last five qwords are

    [SHARED_A][SHARED_B][FACTORY][SHARED_D][SHARED_E]

Only `FACTORY` is per class and lives in `.text`; the other four slots are the
same four function pointers in all 369 tables, so the five-word tail identifies
the family. Scanning for that tail reproduces every client facet in the build. The
class NAME is then recovered without Ghidra: read the rip-relative string operand
the factory passes to `CreateByName`.

BUILD SCOPE: THE SHARED SLOTS MOVE, THE SHAPE DOES NOT
-----------------------------------------------------
The four shared slots are function pointers inside `.text`, so they move whenever
`.text` grows; the table layout and the factory body do not change. That is the
whole difference between 1.400 and 1.460:

    slot        1.400 (sha 8654f01d)    1.460 (sha 30fe6461)    delta
    SHARED_A    0x1406c7b30             0x1406c7cd0             +0x1a0
    SHARED_B    0x1416a1340             0x1416a1f50             +0xc10
    SHARED_D    0x14171a8b0             0x14171b6d0             +0xc20
    SHARED_E    0x1417aae90             0x1417abdd0             +0xf40

None of the four 1.400 words occurs anywhere in the 1.460 image (0 raw-qword
hits), which is why a 1.400-pinned scan reported `0 tables` on a build that still
contains all 368 facets. To re-derive the tail on a new build:

  1. find a known class-name string, e.g. b"GameRigidBodyComponentClientFacet";
  2. take the factory that loads it, i.e. the `lea rXX,[rip+disp]` feeding
     `CreateByName` (the string's xref sites tell you which function);
  3. search `.rdata` for that factory address as a qword: the four values around
     it are the new shared slots;
  4. repeat for the ANCHORS below and re-measure the counts.

When the scan comes back empty this prints which pinned shared word is missing, so
a build move shows up as evidence instead of a bare zero.

VALIDATION
----------
`--check` refuses to write unless all of these still hold on the target build:

* every resolved name ends in `ClientFacet` (the table family is exactly the
  client facets, so a stray name means the signature drifted);
* 368 distinct names over 369 tables, with `GameRigidBodyComponentClientFacet`
  the only duplicate;
* the position facets and `GameRigidBodyComponentClientFacet` resolve to the VAs
  measured on this build.

The 1.460 run reproduces 369 tables and the same 368 names as 1.400, character for
character, which is the cross-check on the re-derived signature: a wrong tail or a
wrong name operand would not land on the old build's name set.

A name that stops resolving is a hard failure, not a silently dropped row: the
previous version of the component registry in this repo went wrong exactly by
degrading quietly. Name resolution reads `lea`/`mov` rip-relative operands with the
standard library only, so a checkout without Capstone still resolves names.

Usage:
    python reverse/tools/scan-client-facets.py [--exe PATH] [--check] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from catalog import PE  # noqa: E402

# The kind layout put this file one level deeper than the reorg assumed:
# `parents[2]` is `reverse/`, so every path below resolved one level too high.
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "research" / "derived" / "client-facet-factories.json"

BUILD_SHA256 = "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033"

# The five-word table tail. Slot 2 is the per-class factory; the other four are the
# same function pointers in every table of this build (see BUILD SCOPE above).
TAIL = (0x1406C7CD0, 0x1416A1F50, None, 0x14171B6D0, 0x1417ABDD0)

# Independently established anchors: class -> factory VAs measured by hand from the
# decompiled factory body (`CreateByName` name argument) on this build. A name may
# legitimately own more than one table (`GameRigidBodyComponentClientFacet` owns two).
ANCHORS: dict[str, tuple[int, ...]] = {
    "PlayerPositionTrackingComponentClientFacet": (0x142D00110,),
    "PositionInTheWorldComponentClientFacet": (0x145C21B20,),
    "PositionalTicketingComponentClientFacet": (0x142606910,),
    "GameRigidBodyComponentClientFacet": (0x141699AB0, 0x141699AC0),
}

EXPECTED_DISTINCT = 368
EXPECTED_TABLES = 369


def _sections(pe: PE) -> tuple[int, int] | None:
    """(start, end) of the section holding the first anchor factory."""
    probe = next(iter(ANCHORS.values()))[0]
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


def tail_presence(pe: PE) -> list[tuple[int, bool]]:
    """Which pinned shared tail words still occur in the image, and which do not.

    A build that moved the shared slots yields zero tables and no other symptom, so
    this turns "0 tables" into evidence about what actually drifted.
    """
    return [
        (word, bool(pe.find_all(struct.pack("<Q", word))))
        for word in (TAIL[0], TAIL[1], TAIL[3], TAIL[4])
    ]


def _rip_targets(code: bytes, base: int):
    """Yield the rip-relative memory targets of `lea`/`mov r64,[rip+disp32]`.

    Both encodings are exactly seven bytes (REX.W, opcode, ModRM with mod=00 and
    rm=101, disp32), so the target is `site + 7 + disp` without a disassembler.
    Standard library only: the harness virtualenv has no Capstone, and a resolver
    that cannot import must fail loudly rather than drop names.
    """
    for i in range(len(code) - 7):
        if code[i] not in (0x48, 0x4C, 0x49, 0x4D):  # REX with W set
            continue
        if code[i + 1] not in (0x8D, 0x8B):  # lea / mov
            continue
        if (code[i + 2] & 0xC7) != 0x05:  # mod=00, rm=101 -> [rip+disp32]
            continue
        disp = struct.unpack_from("<i", code, i + 3)[0]
        yield base + i + 7 + disp


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
    if not result["facets"]:
        for word, present in tail_presence(PE(exe)):
            if not present:
                print(f"  shared tail word 0x{word:x} is absent from the image")
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
