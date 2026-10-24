#!/usr/bin/env python3
"""Locate the writer of the local-player entity id by dataflow, not pattern.

`[mgr+8]` is the local player entity id (u64). Two live facts constrain
the writer:
  * it is never executed while the world loads (page watch saw 0 writes);
  * every vtable slot of the manager is a getter, so the store is in
    ordinary code that receives the manager as an argument or loads it
    from the singleton storage (0x14a2fb9f0).

So the writer must be a function that (a) reaches the storage, or (b) takes
the manager pointer and stores to offset 8. We scan .text for the exact
store encodings against any register-based pointer, and separately for the
`[reg+8] = reg` forms reachable near the 61 storage-reference sites. The
output is a short candidate list to disassemble, not a guess.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

# [reg+8] = reg  (64-bit): REX.W 89 /r, mod=01, rm=reg, disp8=0x08
# opcode 0x89; modrm = 01 reg(3) rm(3) with mod=01 => 0b01RRRmmm
# disp8 at +3 must be 0x08.
def scan() -> None:
    pe = PE(Path(default_paths()["exe"]))
    data = pe.data
    text = pe.section(".text")
    raw, rsize, va0 = text["raw"], text["rsize"], text["va"]
    # The manager's own vtable methods live in a contiguous band around
    # 0x146800000-0x146900000 (slots mapped there). A setter is likely in
    # the same translation unit. Scan that band for [reg+8] stores.
    lo, hi = 0x146800000, 0x146900000
    i0 = raw + (lo - va0)
    i1 = raw + (hi - va0)
    hits = []
    for i in range(i0, min(i1, raw + rsize) - 7):
        b0 = data[i]
        if b0 not in (0x48, 0x49, 0x4C):  # REX.W (+ maybe REX.R/B)
            continue
        if data[i + 1] != 0x89:
            continue
        modrm = data[i + 2]
        mod = (modrm >> 6) & 3
        if mod != 1:
            continue
        if data[i + 3] != 0x08:
            continue
        rm = modrm & 7
        reg = (modrm >> 3) & 7
        va = va0 + (i - raw)
        hits.append((va, rm, reg))
    print(f"{len(hits)} `[reg+8] = reg` stores in 0x{lo:x}-0x{hi:x}")
    for va, rm, reg in hits:
        print(f"  {va:#x}  [r{rm}+8] = r{reg}")


if __name__ == "__main__":
    scan()
