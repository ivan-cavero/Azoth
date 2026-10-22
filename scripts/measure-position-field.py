"""Locate and characterise the channel-1 position field on the installed build.

WHY THIS EXISTS
===============
alc.py locates the position by the float32 0.05 marker rather than a fixed offset, because
the block moves as the body grows. On 1.460 the marker turned up at TWO dominant body
offsets (91 and 89), which raises a question the plan cannot leave open: is the position one
field that shifted, or two different fields (an anchor and a live value) that the locator
cannot tell apart?

This dumps the evidence needed to decide: positions grouped by marker offset, plus the raw
ordered series, so a human can see whether one group is constant and the other moves.

Usage:
    python scripts/measure-position-field.py .azoth/logs/world.log
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "world" / "src"))
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

MARKER = b"\x3d\x4c\xcc\xcd"
WIRE_INPUT = 0x635


def iter_events(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            brace = line.find("{")
            if brace < 0:
                continue
            try:
                yield json.loads(line[brace:])
            except ValueError:
                continue


def decode_varint(buf: bytes, off: int) -> tuple[int, int]:
    b0 = buf[off]
    n = 0
    while n < 5 and b0 & (0x80 >> n):
        n += 1
    if n == 0:
        return b0, off + 1
    n = min(n, 4)
    low_bits = 7 - n
    value = b0 & ((1 << low_bits) - 1)
    for i in range(n):
        value |= buf[off + 1 + i] << (low_bits + 8 * i)
    return value, off + 1 + n


def split_records(datagram: bytes) -> list[tuple[int, bytes]]:
    if len(datagram) < 4:
        return []
    type_byte = datagram[0]
    if not (type_byte & 0x80) or (type_byte & 0x7E):
        return []
    body = datagram[4:]
    if type_byte & 0x01:
        try:
            body = decompress_lz4_block(body)
        except ValueError:
            return []
    out: list[tuple[int, bytes]] = []
    off = 0
    channel = 0
    seq = 0
    rel = 0
    while off < len(body):
        flags = body[off]
        off += 1
        if flags & 0x40:                       # MF_NO_LENGTH
            size = len(body) - off
        else:
            if off + 2 > len(body):
                break
            size = (body[off] << 8) | body[off + 1]
            off += 2
        if flags & 0x20:                       # MF_DATA_CHANNEL
            if off >= len(body):
                break
            channel = body[off]
            off += 1
        if flags & 0x04:                       # MF_CHUNKS
            off += 2
        if flags & 0x08:                       # MF_SEQUENTIAL_ID
            seq = (seq + 1) & 0xFFFF
        else:
            if off + 2 > len(body):
                break
            seq = (body[off] << 8) | body[off + 1]
            off += 2
        if flags & 0x10:                       # MF_SEQUENTIAL_REL_ID
            rel = (rel + 1) & 0xFFFF
        else:
            if off + 2 > len(body):
                break
            rel = (body[off] << 8) | body[off + 1]
            off += 2
        out.append((channel, body[off:off + size]))
        off += size
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("--series", type=int, default=24)
    args = ap.parse_args()

    by_offset: dict[int, list[tuple[float, float]]] = defaultdict(list)
    series: list[tuple[int, float, float, int]] = []
    tails: dict[int, Counter] = defaultdict(Counter)

    for ev in iter_events(Path(args.log)):
        if ev.get("event") != "app-data":
            continue
        raw = ev.get("raw")
        if not raw:
            continue
        try:
            datagram = bytes.fromhex(raw)
        except ValueError:
            continue
        for channel, payload in split_records(datagram):
            if channel != 1 or len(payload) < 26:
                continue
            if int.from_bytes(payload[4:8], "big") != len(payload) - 8:
                continue
            if payload[24:26] != b"\x00\x01":
                continue
            try:
                wire, off = decode_varint(payload, 26)
            except IndexError:
                continue
            if wire != WIRE_INPUT:
                continue
            body = payload[off:]
            idx = body.find(MARKER)
            if idx < 0 or idx + 20 > len(body):
                continue
            a, b, x, y = struct.unpack(">4f", body[idx + 4:idx + 20])
            by_offset[idx].append((round(x, 3), round(y, 3)))
            series.append((idx, round(x, 3), round(y, 3), len(payload)))
            tails[idx][len(body) - idx] += 1

    print(f"samples: {len(series)}")
    print()
    print("== positions grouped by marker body offset ==")
    for off in sorted(by_offset, key=lambda k: -len(by_offset[k]))[:8]:
        vals = by_offset[off]
        xs = [v[0] for v in vals]
        ys = [v[1] for v in vals]
        print(f"  offset {off}: n={len(vals)} distinct={len(set(vals))} "
              f"x {min(xs):.2f}..{max(xs):.2f}  y {min(ys):.2f}..{max(ys):.2f}")
        for pos, n in Counter(vals).most_common(4):
            print(f"      {pos}  x{n}")
        print(f"      bytes after marker: {dict(tails[off].most_common(3))}")

    print()
    print(f"== ordered series (first {args.series}) ==")
    print("   marker_offset      x            y     payload")
    for off, x, y, size in series[:args.series]:
        print(f"   {off:13d}  {x:11.3f}  {y:11.3f}  {size:6d}")

    # A transition table: which distinct positions follow which. A two-state flip
    # shows up as two rows that are each other's only successor.
    print()
    print("== transition table (top 8) ==")
    trans: Counter = Counter()
    for p, q in zip(series, series[1:]):
        trans[(p[1], p[2], q[1], q[2])] += 1
    for (x0, y0, x1, y1), n in trans.most_common(8):
        print(f"   ({x0:9.3f},{y0:9.3f}) -> ({x1:9.3f},{y1:9.3f})  x{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
