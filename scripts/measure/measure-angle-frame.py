"""Verify the channel-1 angle frame and the replication cadence on the installed build.

WHY THIS EXISTS
===============
Two of the plan's build-scoped dependencies cannot be checked by reading code, because they
are properties of the CLIENT, not of our server:

  * the angle pair's frame -- is `a` the camera yaw with forward = (-sin, cos), as measured
    on 1.400? Getting this backwards reports a forward walk as a sideways one, which is a
    mistake this project has already made once.
  * the position block's shape -- does one record carry ONE position (the idle anchor) or
    FIVE (the sliding buffer measured on 1.400)?

Both are answered by correlating displacement with the reported angle over a real session,
so this needs a world.log from a session where the player actually moved -- no probe, no
client launch.

Method: for every consecutive pair of input records that both carry a position, compute the
heading of the displacement and compare it against `a`. A constant offset means the frame is
intact and the offset IS the frame convention.

Usage:
    python scripts/measure-angle-frame.py .azoth/logs/world.log
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "world" / "src"))
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

MARKER = b"\x3d\x4c\xcc\xcd"
WIRE_INPUT = 0x635
MF_CHUNKS = 0x04
MF_SEQUENTIAL_ID = 0x08
MF_SEQUENTIAL_REL_ID = 0x10
MF_DATA_CHANNEL = 0x20
MF_NO_LENGTH = 0x40


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
    if n >= 5:
        n = 4
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
        if flags & MF_NO_LENGTH:
            size = len(body) - off
        else:
            if off + 2 > len(body):
                break
            size = (body[off] << 8) | body[off + 1]
            off += 2
        if flags & MF_DATA_CHANNEL:
            if off >= len(body):
                break
            channel = body[off]
            off += 1
        if flags & MF_CHUNKS:
            off += 2
        if flags & MF_SEQUENTIAL_ID:
            seq = (seq + 1) & 0xFFFF
        else:
            if off + 2 > len(body):
                break
            seq = (body[off] << 8) | body[off + 1]
            off += 2
        if flags & MF_SEQUENTIAL_REL_ID:
            rel = (rel + 1) & 0xFFFF
        else:
            if off + 2 > len(body):
                break
            rel = (body[off] << 8) | body[off + 1]
            off += 2
        out.append((channel, body[off:off + size]))
        off += size
    return out


def decode_input(payload: bytes):
    """Return (yaw, pitch, x, y, body) or None.

    Container: [u32 BE crc32][u32 BE len][target 16][00 01][varint type][body].
    """
    if len(payload) < 26:
        return None
    if int.from_bytes(payload[4:8], "big") != len(payload) - 8:
        return None
    if payload[24:26] != b"\x00\x01":
        return None
    try:
        wire, off = decode_varint(payload, 26)
    except IndexError:
        return None
    if wire != WIRE_INPUT:
        return None
    body = payload[off:]
    idx = body.find(MARKER)
    if idx < 0 or idx + 20 > len(body):
        return None
    a, b, x, y = struct.unpack(">4f", body[idx + 4:idx + 20])
    return a, b, x, y, body, idx


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    args = ap.parse_args()

    samples: list[tuple[float, float, float, float]] = []  # ts_order, yaw, x, y
    # The trailing float block shape: how many (a,b,x,y) quads follow the marker.
    quad_counts: Counter = Counter()
    tail_floats: Counter = Counter()
    events = 0

    for ev in iter_events(Path(args.log)):
        events += 1
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
            if channel != 1:
                continue
            decoded = decode_input(payload)
            if decoded is None:
                continue
            a, b, x, y, body, idx = decoded
            samples.append((float(len(samples)), a, x, y))
            # How many float32 fit after the marker, and how many of the trailing
            # quads look like another position (a plausible world coordinate)?
            remaining = len(body) - (idx + 4)
            tail_floats[remaining] += 1
            n_quads = remaining // 16
            plausible = 0
            for q in range(n_quads):
                base = idx + 4 + q * 16
                if base + 20 > len(body):
                    break
                _, _, qx, qy = struct.unpack(">4f", body[base:base + 16])
                if 1000.0 < qx < 20000.0 and 1000.0 < qy < 20000.0:
                    plausible += 1
            quad_counts[plausible] += 1

    print(f"events parsed: {events}")
    print(f"input samples with a position: {len(samples)}")
    print()
    print("== the position block's shape ==")
    print("  plausible (a,b,x,y) quads found after the marker, per record:")
    for n, c in sorted(quad_counts.items()):
        print(f"    {n} quads: x{c}")
    print("  bytes after the marker+4, per record (top 10):")
    for n, c in tail_floats.most_common(10):
        print(f"    {n} B: x{c}")

    if len(samples) < 2:
        print("\nnot enough samples for a heading analysis")
        return 0

    # --- heading vs yaw -----------------------------------------------------
    # forward = (-sin(yaw), cos(yaw))  =>  heading = yaw + 90 degrees.
    # So (heading_deg - yaw_deg) should cluster at +90 if the frame is intact.
    deltas: Counter = Counter()
    displacements = 0
    still = 0
    for (_, y0, x0, yy0), (_, y1, x1, yy1) in zip(samples, samples[1:]):
        dx = x1 - x0
        dy = yy1 - yy0
        dist = math.hypot(dx, dy)
        if dist < 0.05:          # below the noise floor: not a displacement
            still += 1
            continue
        displacements += 1
        heading_deg = math.degrees(math.atan2(dy, dx))
        yaw_deg = math.degrees(y1)
        delta = (heading_deg - yaw_deg) % 360.0
        deltas[round(delta / 5.0) * 5 % 360] += 1

    print()
    print("== heading vs reported yaw ==")
    print(f"  consecutive pairs: {len(samples) - 1}  (still: {still}, displacements: {displacements})")
    if displacements:
        print("  (heading - yaw) mod 360, bucketed to 5 degrees, top 12:")
        for deg, c in deltas.most_common(12):
            pct = 100.0 * c / displacements
            print(f"    {deg:5d} deg: x{c}  ({pct:.1f}%)")

        # The frame test: if +90 dominates, forward = (-sin, cos) holds on this build.
        top_deg, top_c = deltas.most_common(1)[0]
        print()
        print(f"  dominant offset: {top_deg} deg ({100.0 * top_c / displacements:.1f}% of displacements)")
        if 85 <= top_deg <= 95:
            print("  VERDICT: forward = (-sin(yaw), cos(yaw)) CONFIRMED -- heading = yaw + 90 deg.")
        elif top_deg == 0:
            print("  VERDICT: forward = (cos(yaw), sin(yaw)) -- the frame is the OTHER convention.")
        else:
            print(f"  VERDICT: neither convention; offset {top_deg} deg needs explaining.")

        # The in-frame decomposition, which is what a correction would have to use.
        fwd = lat = 0.0
        for (_, y0, x0, yy0), (_, y1, x1, yy1) in zip(samples, samples[1:]):
            dx = x1 - x0
            dy = yy1 - yy0
            yaw = y1
            # forward unit vector per the confirmed convention
            fx, fy = -math.sin(yaw), math.cos(yaw)
            fwd += dx * fx + dy * fy
            lat += dx * (-fy) + dy * fx
        print(f"  in-frame totals over the session: forward {fwd:+.3f} u, lateral {lat:+.3f} u")
        if abs(fwd) + abs(lat) > 1e-6:
            print(f"  lateral share of motion: {100.0 * abs(lat) / (abs(fwd) + abs(lat)):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
