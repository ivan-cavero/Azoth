#!/usr/bin/env python3
"""Fast rip-relative xref scan (one pass, in-memory, no per-byte reparse)."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    text = pe.section(".text")
    data = pe.data
    raw, rsize, va0 = text["raw"], text["rsize"], text["va"]
    lo, hi = int(sys.argv[1], 16), int(sys.argv[2], 16)
    buf = data[raw : raw + rsize]
    hits = []
    # A rip-relative disp32 ends at its instruction; the instruction end VA
    # = va0 + i + 4 + (ilen-4). Try the common ilen range 6..9.
    n = len(buf) - 4
    for i in range(n):
        disp = struct.unpack_from("<i", buf, i)[0]
        if disp == 0:
            continue
        end_va = va0 + i + 4
        for ilen in range(3, 10):
            t = end_va + (ilen - 4)
            if lo <= t <= hi:
                hits.append((hex(end_va - ilen), hex(t)))
                break
        if len(hits) > 40:
            break
    for h in hits:
        print(*h)
    print(len(hits), "refs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
