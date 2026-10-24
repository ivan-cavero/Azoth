#!/usr/bin/env python3
"""Find the corpus function that CONTAINS a VA (not just one that starts there).

`scripts/corpus-fn.py` looks up an exact function entry VA. When a backtrace gives
a return address *inside* a function, the useful question is "which function is
this?". The corpus `.idx` gives every function start; the containing range comes
from the block header in the shard (`########## <start>-<end> status=.. name=..`).

Usage:
  python scripts/corpus-contains.py 0x141004235 0x14107fd1b 0x14147e892
"""

from __future__ import annotations

import bisect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDS = ROOT / "reverse" / "builds"


def build_dir() -> Path:
    dirs = sorted(p for p in BUILDS.iterdir() if (p / "corpus" / "shards").is_dir())
    if not dirs:
        raise SystemExit("no corpus found under reverse/builds/*/corpus/shards")
    return dirs[-1]


def load_index(shards: Path) -> tuple[list[int], list[tuple[int, str]]]:
    starts: list[int] = []
    rows: list[tuple[int, str]] = []
    for idx in shards.glob("*.idx"):
        for line in idx.open(encoding="utf-8", errors="replace"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            try:
                va = int(parts[0], 16)
            except ValueError:
                continue
            starts.append(va)
            rows.append((va, parts[3]))
    order = sorted(range(len(starts)), key=lambda i: starts[i])
    return [starts[i] for i in order], [rows[i] for i in order]


def header_for(shard_file: Path, va: int) -> str | None:
    needle = f"########## {va:x}-"
    with shard_file.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(needle):
                return line.strip()
    return None


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    b = build_dir()
    shards = b / "corpus" / "shards"
    starts, rows = load_index(shards)
    for raw in argv:
        va = int(raw, 16)
        i = bisect.bisect_right(starts, va) - 1
        if i < 0:
            print(f"{raw}: before the first function")
            continue
        cand_va, shard = rows[i]
        hdr = header_for(shards / shard, cand_va)
        print(f"{raw} -> {hdr} (start {cand_va:x})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
