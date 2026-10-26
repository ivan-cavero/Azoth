#!/usr/bin/env python3
"""Fast single-pass xref map for a PE: one scan, many lookups.

The naive approach (scan .text per query) is O(n) per string and times out on a
400 MB binary. This builds {target_va: [insn_file_offsets]} once.

Usage:
  python reverse/tools/xrefmap.py dump --lo <hex> --hi <hex>   # strings the
      code in that VA window loads (its key table), one scan
  python reverse/tools/xrefmap.py xrefs --needle <str> [--needle ...]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths, decomp_work  # noqa: E402
from catalog import PE  # noqa: E402

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


def cached_map(
    exe: Path, pe: PE, cache: Path, *, rebuild: bool
) -> dict[int, list[int]]:
    """Persist the one-pass map per executable so later queries are O(1) loads."""
    stat = exe.stat()
    identity = {
        "path": str(exe.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if not rebuild and cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("exe") == identity:
                print(
                    f"reusing {len(saved['map'])} xref targets from {cache}",
                    file=sys.stderr,
                )
                return {int(va, 16): offsets for va, offsets in saved["map"].items()}
        except (OSError, ValueError, KeyError, TypeError):
            pass

    print("building xref map (one pass)...", file=sys.stderr)
    result = build_map(pe)
    cache.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exe": identity,
        "map": {f"{va:x}": offsets for va, offsets in result.items()},
    }
    temporary = cache.with_suffix(cache.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"
    )
    temporary.replace(cache)
    print(f"saved {len(result)} xref targets to {cache}", file=sys.stderr)
    return result


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
        needle = n.encode()
        offs = pe.find_all(needle + b"\0") or pe.find_all(needle)
        if not offs:
            print(f"{n!r}: not found in the executable")
            continue
        for fo in offs[:4]:
            va = pe.foff_to_va(fo)
            if va is None:
                continue
            sites = xmap.get(va, [])
            site_vas = [pe.foff_to_va(site) for site in sites[:6]]
            rendered = [hex(site) if site is not None else "?" for site in site_vas]
            print(f"{n!r} @{hex(va)} xrefs={len(sites)} {rendered}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dump", "xrefs"])
    ap.add_argument("--lo")
    ap.add_argument("--hi")
    ap.add_argument("--needle", action="append", default=[])
    ap.add_argument("--exe")
    ap.add_argument(
        "--cache",
        help="xref-map cache (default: reverse/builds/<sha256>/xrefmap.json)",
    )
    ap.add_argument(
        "--rebuild", action="store_true", help="discard and rebuild the cached map"
    )
    args = ap.parse_args()
    p = default_paths()
    exe = Path(args.exe) if args.exe else p["exe"]
    pe = PE(exe)
    cache = Path(args.cache) if args.cache else decomp_work(exe) / "xrefmap.json"
    xmap = cached_map(exe, pe, cache, rebuild=args.rebuild)
    if args.mode == "dump":
        dump_window(pe, xmap, int(args.lo, 16), int(args.hi, 16))
    else:
        xrefs_for(pe, xmap, args.needle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
