"""Find rip-relative lea references to a substring (mid-string xrefs).

xrefmap.py only keys the string START; log messages referenced from the
middle of a composed literal (or via a different base) get missed. This
scans .text for every `lea r64, [rip+disp]` whose target VA falls INSIDE
a given needle string, then prints the surrounding function context.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from catalog import PE  # noqa: E402

REX_W = (0x48, 0x4C, 0x49, 0x4D)


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    needle = sys.argv[1].encode()
    i = pe.data.find(needle)
    if i == -1:
        print("needle not found")
        return 1
    lo = pe.foff_to_va(i)
    hi = lo + len(needle)
    print(f"needle VA range [{hex(lo)}, {hex(hi)})")

    text = pe.section(".text")
    base_va, raw = text["va"], text["raw"]
    hits = []
    data = pe.data
    for off in range(raw, raw + text["rsize"] - 7):
        if data[off] not in REX_W or data[off + 1] != 0x8D:
            continue
        if (data[off + 2] & 0xC7) != 0x05:
            continue
        disp = struct.unpack_from("<i", data, off + 3)[0]
        tgt = base_va + (off - raw) + 7 + disp
        if lo <= tgt < hi:
            hits.append(base_va + (off - raw))
    print(f"{len(hits)} lea-xrefs: {[hex(h) for h in hits]}")

    # Fallback: absolute references (mov r, imm64 or pointer tables) —
    # scan every 8-byte aligned qword in .rdata for the string VA.
    rdata = pe.section(".rdata")
    abs_hits = []
    rd = pe.data
    for off in range(rdata["raw"], rdata["raw"] + rdata["rsize"] - 8, 4):
        q = struct.unpack_from("<Q", rd, off)[0]
        if lo <= q < hi:
            va = rdata["va"] + (off - rdata["raw"])
            abs_hits.append(va)
    print(f"{len(abs_hits)} abs-qword refs in .rdata: {[hex(h) for h in abs_hits[:10]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
