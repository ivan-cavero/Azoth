#!/usr/bin/env python3
"""Find callsites of the three spawn getters inside FUN_14644a070."""
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
    raw, rsize = text["raw"], text["rsize"]
    lo, hi = 0x14644A000, 0x14644B000  # FUN_14644a070 body
    fo_lo = pe.va_to_foff(lo)
    fo_hi = pe.va_to_foff(hi)
    for target in (0x145A92370, 0x145A905C0, 0x145A923C0):
        hits = []
        for fo in range(fo_lo, fo_hi):
            if pe.data[fo] == 0xE8:
                rel = struct.unpack_from("<i", pe.data, fo + 1)[0]
                va = text["va"] + (fo - raw)
                if va + 5 + rel == target:
                    hits.append(hex(va))
        print(hex(target), "callsites:", hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
