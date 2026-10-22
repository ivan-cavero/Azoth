"""Map message descriptors to their getters, from the 1.460 decompiled corpus.

WHY THIS EXISTS
===============
`research/atlas/presence-codecs.json` records that the static route which decoded the movement
family on 1.400 is gone on 1.460: the name and GUID strings have zero static referrers, both
16-byte GUID forms occur zero times, and `FUN_1407de270` (the descriptor builder recorded for
1.400) has no callers. Its conclusion was that the descriptor tables are assembled at runtime and
the six presence codec layouts need live instrumentation.

That conclusion was about a specific function address, not about the route. This script tests the
route on the corpus that now exists for 1.460 and finds the builder under a new address:

    FUN_1461aa880   called 3,520 times, each from a tiny getter shaped like

        apuStack_48[0] = &UNK_<descriptor address>;
        uVar1 = FUN_1461aa880(apuStack_48);
        DAT_<cache> = uVar1;

So every descriptor IS statically reachable: the getter loads its address, the builder turns it
into a runtime descriptor, and the result is cached. What the 1.400 route additionally had was a
codec facet stored at descriptor+0x48; whether 1.460 does the same is the next question, and this
script collects the addresses that would answer it.

WHAT IT PRODUCES
================
A table of `descriptor address -> getter function`, sorted by address, so a descriptor of interest
(the presence codecs sit near 0x1485800E0) can be traced to the function that builds it, and from
there to the codec facet it installs.

Usage:
    python scripts/map-descriptors.py
    python scripts/map-descriptors.py --near 1485800e0 --radius 4096
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CORPUS = (
    Path(__file__).resolve().parents[1]
    / "reverse" / "builds"
    / "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033"
    / "corpus" / "shards"
)

# A shard entry header, then a getter body.
FUNC_RE = re.compile(r"^FUNC (FUN_[0-9a-f]+) entry=([0-9a-f]+)")
# The descriptor load the getters share.
LOAD_RE = re.compile(r"apuStack_48\[0\] = &UNK_([0-9a-f]+);")
# The builder call, whose presence marks the getter as a descriptor getter.
BUILDER = "FUN_1461aa880"
# The cache store that completes the shape.
CACHE_RE = re.compile(r"^(DAT_[0-9a-f]+) = uVar1;")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--near", default=None,
                    help="report only descriptors within --radius of this hex address")
    ap.add_argument("--radius", type=lambda s: int(s, 0), default=0x2000)
    ap.add_argument("--out", default=None, help="write the full map as JSON here")
    args = ap.parse_args()

    shards = sorted(Path(args.corpus).glob("shard-*.c"))
    if not shards:
        print(f"no shards under {args.corpus}")
        return 1

    # getter address -> (descriptor address, cache symbol)
    found: dict[str, tuple[str, str | None]] = {}
    for shard in shards:
        current: str | None = None
        descriptor: str | None = None
        is_getter = False
        for line in shard.read_text(encoding="utf-8", errors="replace").splitlines():
            header = FUNC_RE.match(line)
            if header:
                current = header.group(1)
                descriptor = None
                is_getter = False
                continue
            load = LOAD_RE.search(line)
            if load and current:
                descriptor = load.group(1)
                continue
            if BUILDER in line and current:
                is_getter = True
                continue
            cache = CACHE_RE.match(line.strip())
            if cache and current and is_getter and descriptor:
                found[current] = (descriptor, cache.group(1))
                descriptor = None
                is_getter = False

    print(f"descriptor getters found: {len(found)}")
    if not found:
        print("FAIL: the getter shape was not matched; the corpus layout may have changed")
        return 1

    by_descriptor = sorted(found.items(), key=lambda kv: int(kv[1][0], 16))
    low = int(by_descriptor[0][1][0], 16)
    high = int(by_descriptor[-1][1][0], 16)
    print(f"descriptor address range: 0x{low:x} .. 0x{high:x}")

    if args.near:
        target = int(args.near, 16)
        near = [
            (getter, desc, cache)
            for getter, (desc, cache) in by_descriptor
            if abs(int(desc, 16) - target) <= args.radius
        ]
        print(f"\ndescriptors within 0x{args.radius:x} of 0x{target:x}: {len(near)}")
        for getter, desc, cache in near:
            print(f"  descriptor 0x{desc}  getter {getter}  cache {cache}")
        if not near:
            print("  (none — widen --radius or check the address)")

    if args.out:
        import json
        out = {
            "build_sha256": "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033",
            "builder": BUILDER,
            "getter_count": len(found),
            "descriptors": [
                {"descriptor": desc, "getter": getter, "cache": cache}
                for getter, (desc, cache) in by_descriptor
            ],
        }
        Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
