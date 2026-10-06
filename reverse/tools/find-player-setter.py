#!/usr/bin/env python3
"""Find who writes the local-player pointer at [manager+8].

The 13->14 spawn gate (0x146800d10) returns [mgr+8] where mgr comes from
the lazy singleton 0x141026080. The replica layer is supposed to create
the local player and store it there. Scan all `call 0x141026080` sites
and flag the ones that write [rax+8] shortly after the call.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    text = pe.section(".text")
    raw, rsize = text["raw"], text["rsize"]
    data = pe.data
    target = 0x141026080
    writers = []
    for i in range(raw, raw + rsize - 5):
        if data[i] != 0xE8:
            continue
        rel = struct.unpack_from("<i", data, i + 1)[0]
        va = text["va"] + (i - raw)
        if va + 5 + rel != target:
            continue
        # inspect the next 32 bytes for ANY write to [rax+8] form:
        # REX.W (48/4c) 89 /r where modrm mod=01 rm=rax disp8=08, i.e.
        # 48 89 48/50/58/60/68/70/78 08 or 4c 89 4x/5x/6x 08
        window = data[i + 5 : i + 37]
        hit = None
        for off in range(len(window) - 3):
            b0, b1, b2, b3 = window[off : off + 4]
            if b0 in (0x48, 0x4C) and b1 == 0x89 and (b2 & 0xC7) == 0x40 and b3 == 0x08:
                reg = ((b2 >> 3) & 7) | (0x8 if b0 == 0x4C else 0)
                rm = b2 & 7
                names = "ax cx dx bx sp bp si di".split()
                regs = names + [f"r{n}" for n in (8, 9, 10, 11, 12, 13, 14, 15)]
                hit = f"mov [rax+8], {regs[reg]} @+{off}"
                break
        if hit:
            writers.append((hex(va), hit))
    for va, w in writers:
        print(va, w)
    print(len(writers), "writers found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
