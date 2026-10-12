#!/usr/bin/env python3
"""Print the cached pseudocode of one function from the local corpus, by VA.

The corpus (reverse/builds/<sha>/corpus/shards) is the bulk Ghidra pseudocode dump
of every .pdata function. Each shard has a `.idx` line `<va>\t<status>\t<bytes>\t<shard>`.
This is a fast reader for that; use `python az.py re decompile` when the function
is not in the corpus or you need a fresh decompile.

Usage:
  python scripts/corpus-fn.py 0x1413fb700
  python scripts/corpus-fn.py 1413fb700 1413789c0
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDS = ROOT / "reverse" / "builds"


def build_dir() -> Path:
    dirs = sorted(p for p in BUILDS.iterdir() if (p / "corpus" / "shards").is_dir())
    if not dirs:
        raise SystemExit("no corpus found under reverse/builds/*/corpus/shards")
    return dirs[-1]


def shards_dir(b: Path) -> Path:
    return b / "corpus" / "shards"


def lookup(b: Path, va: str) -> None:
    va = va.lower().removeprefix("0x")
    needle = va + "\t"
    for idx in shards_dir(b).glob("*.idx"):
        with idx.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith(needle):
                    _, status, size, shard = line.rstrip("\n").split("\t")
                    print(f"########## {va} status={status} bytes={size} {shard} ##########")
                    text = (shards_dir(b) / shard).read_text(encoding="utf-8", errors="replace")
                    # blocks are separated by lines starting with ##########; a block
                    # begins at its header line ('########## <range> status=.. name=FUN_..')
                    pos = text.find(f"name=FUN_{va}")
                    if pos < 0:
                        print(f"(shard {shard} has no block header for {va})")
                        return
                    start = text.rfind("##########", 0, pos)
                    nxt = text.find("\n##########", pos)
                    end = len(text) if nxt < 0 else nxt
                    print(text[start:end].rstrip())
                    return
    raise SystemExit(f"{va} not found in corpus index")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    b = build_dir()
    print(f"# corpus {b.name}")
    for va in argv:
        lookup(b, va)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
