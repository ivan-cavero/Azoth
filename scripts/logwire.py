"""Shared parsing for the world server's structured log.

WHY THIS EXISTS
===============
Three measurement scripts need to turn a `world.log` line back into (channel, payload) pairs:
the framing rules are the same ones the server applied on the way in, and re-typing them per
script is how a copy drifts and how a typo becomes a wrong number. One implementation, one
place to fix.

The log records every inbound datagram as `raw` hex, so the framing is recovered by walking
it with the flags the client set -- a field is present only when its flag says so
(research/docs/JAVELIN-PROTOCOL.md section 1c). A datagram that does not parse cleanly
yields whatever was decoded before the failure: a partially readable datagram is still
evidence.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "services" / "world" / "src"))
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

# The float32 0.05 that precedes the movement block in a channel-1 body
# (services/world/src/azoth_world/javelin/alc.py).
MARKER = b"\x3d\x4c\xcc\xcd"
# ActionListComponentServerFacet_ReceiveInputFromClient: the only typed message on channel 1.
WIRE_INPUT = 0x635

# MessageRecord flags.
MF_RELIABLE = 0x01
MF_CHUNKS = 0x04
MF_SEQUENTIAL_ID = 0x08
MF_SEQUENTIAL_REL_ID = 0x10
MF_DATA_CHANNEL = 0x20
MF_NO_LENGTH = 0x40
MF_CONNECTING = 0x80


def iter_events(path: Path):
    """Yield each log line's JSON object. Lines without JSON are skipped."""
    with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
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
    n = min(n, 4)
    low_bits = 7 - n
    value = b0 & ((1 << low_bits) - 1)
    for i in range(n):
        value |= buf[off + 1 + i] << (low_bits + 8 * i)
    return value, off + 1 + n


def split_records(datagram: bytes) -> list[tuple[int, bytes]]:
    """Split a post-DTLS datagram into (channel, payload) pairs."""
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
    """Decode a channel-1 payload into its movement fields.

    The payload IS the client's own container (research/docs/JAVELIN-PROTOCOL.md
    section 1f, reconfirmed on 1.460 -- 229,304 of 229,304 records pass both the length
    and the CRC check):

        [u32 BE crc32][u32 BE len][16-byte target][00 01][prefix-varint type][body]

    Returns (yaw, pitch, x, y, body, marker_offset, target_hex) or None.

    The position is located by the 0.05 marker and read at marker+12 as two big-endian
    float32, because the block's body offset is NOT stable: it was 103 on 1.400 and is 91 on
    1.460 for the dominant form. A fixed offset would silently read the wrong field.
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
    target = payload[8:24]
    body = payload[off:]
    idx = body.find(MARKER)
    if idx < 0 or idx + 20 > len(body):
        return None
    yaw, pitch, x, y = struct.unpack(">4f", body[idx + 4:idx + 20])
    return yaw, pitch, x, y, body, idx, target.hex()
