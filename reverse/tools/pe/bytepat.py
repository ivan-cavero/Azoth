#!/usr/bin/env python3
"""Byte-pattern locator: re-derive external RE findings on OUR exe build.

External VAs (e.g. first-light's DTLS patch site 0x145dce8b5) belong to a
different client build and are useless as raw numbers. What survives across
builds is the *instruction shape* around the site. This tool scans .text for
a byte pattern with wildcards and reports every VA hit, so a finding can be
re-anchored in minutes instead of re-decompiled from scratch.

Disk only. Never opens the game process.

Usage:
  python reverse/tools/bytepat.py --exe PATH --pat "48 8B BF ?? ?? 00 00 0F 84"
  python reverse/tools/bytepat.py dtls-verify   # named built-in pattern
  python reverse/tools/bytepat.py --list        # show built-ins
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

# Built-in patterns: (description, hex with ?? wildcards).
# Derived from research/docs/REP-PROTOCOL.md (external Ghidra traces).
PATTERNS: dict[str, tuple[str, str]] = {
    "dtls-verify": (
        "DTLS driver branch: CMP qword ptr [RDI+0x288],0 / JZ <permissive>. "
        "The JZ (6 bytes: 0F 84 <rel32>) is the trust-bypass patch site "
        "(-> JMP E9 <rel32> 90). Displacement varies per build; the CMP "
        "bytes are stable.",
        "48 83 BF 88 02 00 00 00 0F 84 ?? ?? ?? ??",
    ),
}


def parse_pattern(spec: str) -> list[int | None]:
    out: list[int | None] = []
    for tok in spec.split():
        out.append(None if set(tok) == {"?"} else int(tok, 16))
    return out


def scan(data: bytes, lo: int, hi: int, pat: list[int | None]) -> list[int]:
    """All file offsets in [lo, hi) matching the pattern (None = wildcard)."""
    n = len(pat)
    first = [b for b in pat if b is not None]
    if not first:
        raise ValueError("pattern is all wildcards")
    hits: list[int] = []
    start = lo
    first_byte = pat.index(first[0])
    while True:
        i = data.find(bytes([first[0]]), start, hi - n + 1)
        if i < 0:
            return hits
        base = i - first_byte
        if base >= lo and all(
            b is None or data[base + k] == b for k, b in enumerate(pat)
        ):
            hits.append(base)
        start = i + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", nargs="?", help="built-in pattern name or raw hex")
    ap.add_argument("--pat", help="raw hex pattern (overrides name lookup)")
    ap.add_argument("--exe", help="exe path (default: Steam install)")
    ap.add_argument("--list", action="store_true", help="show built-in patterns")
    args = ap.parse_args()

    if args.list or (not args.name and not args.pat):
        for name, (desc, pat) in PATTERNS.items():
            print(f"{name}: {pat}\n  {desc}")
        return 0

    if args.pat:
        desc, spec = "ad-hoc", args.pat
    elif args.name in PATTERNS:
        desc, spec = PATTERNS[args.name]
    else:
        desc, spec = "ad-hoc", args.name
    pat = parse_pattern(spec)

    p = default_paths()
    pe = PE(Path(args.exe) if args.exe else p["exe"])
    text = pe.section(".text")
    hits = scan(pe.data, text["raw"], text["raw"] + text["rsize"], pat)
    print(f"# {desc}")
    print(f"# pattern: {spec}")
    print(f"# .text VA range: {hex(text['va'])}..{hex(text['va'] + text['rsize'])}")
    if not hits:
        print("no hits")
        return 1
    for fo in hits:
        va = pe.foff_to_va(fo)
        print(f"hit foff={hex(fo)} va={hex(va) if va else '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
