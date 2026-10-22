"""Measure the channel-1 input stream and the state stream from a world.log.

WHY THIS EXISTS
===============
The Rust port needs the channel-1 field map and the replication cadence re-measured on the
installed build (docs/PLAN-backend-rust.md section 0.2). The world server logs every inbound
datagram with its raw bytes, so a probe-free session is enough to answer most of it without
launching the client.

What it reports, and the plan item each answers:
  * channel-1 record sizes and body sizes      -> the idle vs moving body forms
  * the 0.05f position marker census           -> is the position locator still valid
  * the decoded position series                -> does the live feed move
  * the yaw/pitch pair                         -> is the angle frame still (yaw, pitch)
  * state-stream record ids and cadence        -> the replication cadence per record

Usage:
    python scripts/measure-world-log.py .azoth/logs/world.log
    python scripts/measure-world-log.py <log> --json out.json
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "world" / "src"))
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

# The float32 0.05 that precedes the movement block in a channel-1 body
# (services/world/src/azoth_world/javelin/alc.py). Big-endian on the wire.
MARKER = b"\x3d\x4c\xcc\xcd"
# Channel-1 wire type: ActionListComponentServerFacet_ReceiveInputFromClient.
WIRE_INPUT = 0x635

# MessageRecord flags (research/docs/JAVELIN-PROTOCOL.md section 1c).
MF_RELIABLE = 0x01
MF_CHUNKS = 0x04
MF_SEQUENTIAL_ID = 0x08
MF_SEQUENTIAL_REL_ID = 0x10
MF_DATA_CHANNEL = 0x20
MF_NO_LENGTH = 0x40
MF_CONNECTING = 0x80


def iter_events(path: Path):
    """Yield each log line's JSON object. Non-JSON lines are skipped silently."""
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
    """The Javelin prefix varint: leading 1-bits of b0 give the continuation count."""
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
    """Split a post-DTLS datagram into (channel, payload) pairs.

    The framing rules are the ones research/docs/JAVELIN-PROTOCOL.md measured; a field is
    present only when its flag says so, which is why this is a walk and not a fixed struct.
    A datagram that does not parse cleanly yields whatever was decoded before the failure,
    because a partially-readable datagram is still evidence.
    """
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
            off += 2  # numChunks
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
        payload = body[off:off + size]
        off += size
        out.append((channel, payload))
    return out


def analyse_channel1(payload: bytes, stats: dict, positions: list) -> None:
    """Decode one channel-1 payload and fold it into `stats`.

    The payload IS the client's own container, not a bare typed message
    (research/docs/JAVELIN-PROTOCOL.md section 1f, measured 2026-10-11 and reconfirmed
    here):

        [u32 BE crc32][u32 BE len][16-byte target][00 01][prefix-varint type][body]

    `len` covers everything after itself, so the container is self-validating: a wrong
    walk shows up as a length mismatch or a CRC mismatch instead of as silently wrong
    offsets. That is why both are checked and counted rather than assumed.
    """
    stats["ch1_total"] += 1
    stats["ch1_size"][len(payload)] += 1
    if len(payload) < 26:
        stats["ch1_short"] += 1
        return
    crc = int.from_bytes(payload[0:4], "big")
    declared = int.from_bytes(payload[4:8], "big")
    if declared != len(payload) - 8:
        stats["ch1_len_mismatch"] += 1
        return
    if zlib.crc32(payload[8:]) & 0xFFFFFFFF != crc:
        stats["ch1_crc_mismatch"] += 1
        return
    stats["ch1_container_ok"] += 1
    if payload[24:26] != b"\x00\x01":
        stats["ch1_no_marker_0001"] += 1
        return
    try:
        wire, off = decode_varint(payload, 26)
    except IndexError:
        stats["ch1_bad_varint"] += 1
        return
    if wire != WIRE_INPUT:
        stats["ch1_other_wire"][wire] += 1
        return
    stats["ch1_target"][payload[8:24].hex()] += 1
    body = payload[off:]
    stats["ch1_body_size"][len(body)] += 1
    # The position locator: marker + 12, two big-endian float32.
    idx = body.find(MARKER)
    if idx < 0:
        stats["ch1_no_position_marker"] += 1
        return
    stats["ch1_marker_count"][body.count(MARKER)] += 1
    if idx + 20 > len(body):
        stats["ch1_marker_truncated"] += 1
        return
    a, b, x, y = struct.unpack(">4f", body[idx + 4:idx + 20])
    stats["ch1_marker_offset"][idx] += 1
    stats["ch1_angles"].append((round(a, 3), round(b, 3)))
    positions.append((x, y))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("--json")
    args = ap.parse_args()

    stats = {
        "ch1_size": Counter(),
        "ch1_body_size": Counter(),
        "ch1_target": Counter(),
        "ch1_other_wire": Counter(),
        "ch1_marker_offset": Counter(),
        "ch1_marker_count": Counter(),
        "ch1_total": 0,
        "ch1_short": 0,
        "ch1_container_ok": 0,
        "ch1_len_mismatch": 0,
        "ch1_crc_mismatch": 0,
        "ch1_no_marker_0001": 0,
        "ch1_bad_varint": 0,
        "ch1_no_position_marker": 0,
        "ch1_marker_truncated": 0,
        "ch1_angles": [],
    }
    positions: list[tuple[float, float]] = []
    state_records: Counter = Counter()
    state_events = 0
    state_ts: list[str] = []
    state_size: Counter = Counter()
    events = 0

    for ev in iter_events(Path(args.log)):
        events += 1
        name = ev.get("event")
        if name == "app-data":
            raw = ev.get("raw")
            if not raw:
                continue
            try:
                datagram = bytes.fromhex(raw)
            except ValueError:
                continue
            for channel, payload in split_records(datagram):
                if channel == 1:
                    analyse_channel1(payload, stats, positions)
        elif name == "state-stream":
            state_events += 1
            if ev.get("ts"):
                state_ts.append(ev["ts"])
            ids = ev.get("records")
            if isinstance(ids, list):
                for rid in ids:
                    state_records[rid if isinstance(rid, int) else json.dumps(rid)] += 1
            if ev.get("size"):
                state_size[ev["size"]] += 1

    # --- report -------------------------------------------------------------
    print(f"events parsed: {events}")
    print()
    print("== channel 1 (client -> server input stream) ==")
    print(f"typed input records ({WIRE_INPUT:#x}): {stats['ch1_total']}")
    print(f"  container valid (len+crc): {stats['ch1_container_ok']}")
    print(f"  length-field mismatch:     {stats['ch1_len_mismatch']}")
    print(f"  crc32 mismatch:            {stats['ch1_crc_mismatch']}")
    print(f"  not 00 01 prefixed:        {stats['ch1_no_marker_0001']}")
    print(f"  other wire types:          {dict(stats['ch1_other_wire'])}")
    with_marker = stats["ch1_total"] - stats["ch1_no_position_marker"]
    print(f"  with position marker:    {with_marker}")
    print(f"  WITHOUT position marker: {stats['ch1_no_position_marker']}")
    print(f"  marker occurrences/rec:  {dict(stats['ch1_marker_count'])}")
    print(f"  marker body offsets:     {dict(sorted(stats['ch1_marker_offset'].items()))}")
    print(f"  distinct target actor ids: {len(stats['ch1_target'])}")
    for tgt, n in stats["ch1_target"].most_common(5):
        print(f"    {tgt}  x{n}")
    print()
    print("  record size distribution (top 20):")
    for size, n in stats["ch1_size"].most_common(20):
        print(f"    {size:6d} B  x{n}")
    print("  body size distribution (top 20):")
    for size, n in stats["ch1_body_size"].most_common(20):
        print(f"    {size:6d} B  x{n}")

    if positions:
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        print()
        print(f"  positions decoded: {len(positions)}")
        print(f"    x range: {min(xs):.4f} .. {max(xs):.4f}")
        print(f"    y range: {min(ys):.4f} .. {max(ys):.4f}")
        print(f"    first:   {positions[0]}")
        print(f"    last:    {positions[-1]}")
        distinct = {(round(x, 2), round(y, 2)) for x, y in positions}
        print(f"    distinct positions (0.01 u): {len(distinct)}")

    if stats["ch1_angles"]:
        yaws = [a[0] for a in stats["ch1_angles"]]
        pitches = [a[1] for a in stats["ch1_angles"]]
        print()
        print(f"  angles decoded: {len(stats['ch1_angles'])}")
        print(f"    a (yaw)   range: {min(yaws):.3f} .. {max(yaws):.3f}  distinct {len(set(yaws))}")
        print(f"    b (pitch) range: {min(pitches):.3f} .. {max(pitches):.3f}  distinct {len(set(pitches))}")

    print()
    print("== state stream (type 0x08 bundles) ==")
    print(f"state-stream events: {state_events}")
    for rid, n in state_records.most_common(20):
        print(f"    record {rid}: x{n}")
    if state_size:
        print("  event size field (top 10):")
        for size, n in state_size.most_common(10):
            print(f"    {size:6d}  x{n}")

    if args.json:
        out = {
            "events": events,
            "channel1": {
                "typed_records": stats["ch1_total"],
                "without_position_marker": stats["ch1_no_position_marker"],
                "marker_offsets": {str(k): v for k, v in stats["ch1_marker_offset"].items()},
                "marker_counts": {str(k): v for k, v in stats["ch1_marker_count"].items()},
                "record_sizes": {str(k): v for k, v in stats["ch1_size"].most_common(50)},
                "body_sizes": {str(k): v for k, v in stats["ch1_body_size"].most_common(50)},
                "targets": dict(stats["ch1_target"]),
                "positions_decoded": len(positions),
                "position_x_range": [min(p[0] for p in positions), max(p[0] for p in positions)] if positions else None,
                "position_y_range": [min(p[1] for p in positions), max(p[1] for p in positions)] if positions else None,
                "yaw_range": [min(a[0] for a in stats["ch1_angles"]), max(a[0] for a in stats["ch1_angles"])] if stats["ch1_angles"] else None,
                "pitch_range": [min(a[1] for a in stats["ch1_angles"]), max(a[1] for a in stats["ch1_angles"])] if stats["ch1_angles"] else None,
            },
            "state_stream": {
                "events": state_events,
                "record_ids": dict(state_records),
                "size_field": {str(k): v for k, v in state_size.most_common(20)},
            },
        }
        Path(args.json).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
