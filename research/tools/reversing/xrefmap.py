#!/usr/bin/env python3
"""Fast single-pass xref map for a PE: one scan, many lookups.

The naive approach (scan .text per query) is O(n) per string and times out on a
400 MB binary. This builds {target_va: [insn_file_offsets]} once.

Usage:
  python research/tools/reversing/xrefmap.py dump --lo <hex> --hi <hex>   # strings the
      code in that VA window loads (its key table), one scan
  python research/tools/reversing/xrefmap.py xrefs --needle <str> [--needle ...]
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

REX_W = (0x48, 0x4C, 0x49, 0x4D)


def build_map(pe: PE) -> dict[int, list[int]]:
    """One pass over .text: every lea r64,[rip+disp32] -> its target VA."""
    text = pe.section(".text")
    data = pe.data
    base_va = text["va"]
    raw = text["raw"]
    hi = raw + text["rsize"] - 7
    out: dict[int, list[int]] = {}
    for i in range(raw, hi):
        if data[i] not in REX_W or data[i + 1] != 0x8D:
            continue
        if (data[i + 2] & 0xC7) != 0x05:
            continue
        disp = struct.unpack_from("<i", data, i + 3)[0]
        tgt = base_va + (i - raw) + 7 + disp
        out.setdefault(tgt, []).append(i)
    return out


def dump_window(pe: PE, xmap: dict[int, list[int]], lo: int, hi: int) -> None:
    """Strings loaded by code whose VA falls in [lo, hi]."""
    text = pe.section(".text")
    base_va, raw = text["va"], text["raw"]
    rows = []
    for tgt, sites in xmap.items():
        for fo in sites:
            va = base_va + (fo - raw)
            if lo <= va <= hi:
                txt_fo = pe.va_to_foff(tgt)
                if txt_fo is None:
                    continue
                s = pe.cstring_at(txt_fo, 80)
                if s and all(32 <= ord(c) < 127 for c in s):
                    rows.append((va, tgt, s))
    rows.sort()
    print(f"{len(rows)} strings loaded by code in [{hex(lo)}, {hex(hi)}]")
    for va, tgt, s in rows:
        print(f"  @{hex(va)} -> {hex(tgt)}  {s!r}")


def xrefs_for(pe: PE, xmap: dict[int, list[int]], needles: list[str]) -> None:
    for n in needles:
        offs = pe.find_all(n.encode() + b"\0")
        if not offs:
            print(f"{n!r}: not NUL-terminated anywhere")
            continue
        for fo in offs[:4]:
            va = pe.foff_to_va(fo)
            if va is None:
                continue
            sites = xmap.get(va, [])
            print(f"{n!r} @{hex(va)} xrefs={len(sites)} {[hex(s) for s in sites[:6]]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dump", "xrefs"])
    ap.add_argument("--lo")
    ap.add_argument("--hi")
    ap.add_argument("--needle", action="append", default=[])
    ap.add_argument("--exe")
    args = ap.parse_args()
    p = default_paths()
    pe = PE(Path(args.exe) if args.exe else p["exe"])
    print("building xref map (one pass)...", file=sys.stderr)
    xmap = build_map(pe)
    print(f"map entries: {len(xmap)}", file=sys.stderr)
    if args.mode == "dump":
        dump_window(pe, xmap, int(args.lo, 16), int(args.hi, 16))
    else:
        xrefs_for(pe, xmap, args.needle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
