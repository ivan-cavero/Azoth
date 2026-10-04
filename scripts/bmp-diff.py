"""Compare two client-rect BMP captures (same size) and report scene motion.

Screenshots are the evidence that the body moved; this quantifies it without a
human eye. A held W that works shifts the whole scene (camera follows), so the
changed-pixel ratio is high and the best 8x8 block match is far from zero.

Usage: python scripts/bmp-diff.py before.bmp after.bmp
"""

from __future__ import annotations

import struct
import sys


def read_bmp(path: str) -> tuple[int, int, bytes]:
    data = open(path, "rb").read()
    if data[:2] != b"BM":
        raise SystemExit(f"{path}: not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    w, h = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    if bpp != 24:
        raise SystemExit(f"{path}: expected 24bpp, got {bpp}")
    row_size = ((w * 3 + 3) // 4) * 4
    return w, h, data[offset : offset + row_size * h]


def luma(pixels: bytes, w: int, h: int, step: int = 3) -> list[list[int]]:
    row_size = ((w * 3 + 3) // 4) * 4
    grid: list[list[int]] = []
    for y in range(0, h, step):
        base = y * row_size
        row = []
        for x in range(0, w, step):
            o = base + x * 3
            row.append((pixels[o] * 29 + pixels[o + 1] * 150 + pixels[o + 2] * 77) >> 8)
        grid.append(row)
    return grid


def main() -> int:
    a_path, b_path = sys.argv[1], sys.argv[2]
    wa, ha, pa = read_bmp(a_path)
    wb, hb, pb = read_bmp(b_path)
    if (wa, ha) != (wb, hb):
        raise SystemExit(f"size mismatch {wa}x{ha} vs {wb}x{hb}")
    ga = luma(pa, wa, ha)
    gb = luma(pb, wb, hb)

    total = 0
    changed = 0
    big = 0
    for ra, rb in zip(ga, gb):
        for va, vb in zip(ra, rb):
            d = abs(va - vb)
            total += 1
            if d > 8:
                changed += 1
            if d > 40:
                big += 1
    print(f"size {wa}x{ha} samples {total}")
    print(f"changed>8 : {changed / total:6.2%}")
    print(f"changed>40: {big / total:6.2%}")

    # Best whole-scene shift: if the camera moved, the after image equals the
    # before image displaced by a few pixels.
    best = None
    for dy in range(-24, 25, 4):
        for dx in range(-24, 25, 4):
            if dx == 0 and dy == 0:
                continue
            acc = 0
            n = 0
            for y in range(max(0, dy), min(len(ga), len(gb) + dy)):
                ra = ga[y]
                rb = gb[y - dy]
                for x in range(max(0, dx), min(len(ra), len(rb) + dx)):
                    acc += abs(ra[x] - rb[x - dx])
                    n += 1
            if n == 0:
                continue
            mad = acc / n
            if best is None or mad < best[0]:
                best = (mad, dx, dy)
    zero = 0
    n = 0
    for ra, rb in zip(ga, gb):
        for va, vb in zip(ra, rb):
            zero += abs(va - vb)
            n += 1
    print(f"mean abs diff at shift (0,0): {zero / n:6.2f}")
    if best:
        print(f"best shift match: mad {best[0]:6.2f} at dx={best[1]} dy={best[2]}")
        if zero / n > 0:
            print(f"motion ratio: {(zero / n) / max(best[0], 0.01):6.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
