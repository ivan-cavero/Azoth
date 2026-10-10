"""The Javelin/AZ "prefix varint" used across every inbound typed message.

WHY THIS MODULE EXISTS
=====================
Every typed Javelin message starts with this encoding, and the state bundle's
record id, its replication seq, and every fragment length use it too. The
existing code treated the message type as a fixed 2-byte tag and the state
bundle's seq as a raw byte, which is wrong in both places and produced two
distinct live failures. This module is the single, tested implementation.

THE ENCODING (derived from the client, not guessed)
---------------------------------------------------
The number of LEADING 1-BITS in the first byte gives the number of
continuation bytes that follow. The first byte's remaining low bits are the
LOWEST bits of the value; the continuation bytes are a little-endian integer
placed above them.

    n = count of leading 1-bits in b0        (0..4)
    shift = 7 - n
    value = (LE(continuation_bytes) << shift) | (b0 & ((1 << shift) - 1))

| first byte      | n | bytes | low bits | capacity |
| --------------- | - | ----- | -------- | -------- |
| 0x00..0x7f      | 0 | 1     | 7        | 2^7      |
| 0x80..0xbf      | 1 | 2     | 6        | 2^14     |
| 0xc0..0xdf      | 2 | 3     | 5        | 2^21     |
| 0xe0..0xef      | 3 | 4     | 4        | 2^28     |
| 0xf0..0xff      | 4 | 5     | 3        | 2^35     |

DERIVATION AND EVIDENCE (build 8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e)
-------------------------------------------------------------------------------------------------
The reader is `FUN_14087b5c0` (0x14087b5c0-0x14087b766), called for the
message type, the state-bundle record id, and the fragment key. Its shape —
one byte, then a branch ladder at 0x80/0xc0/0xe0/0xf0 that pulls 1/2/3/4 more
bytes and ORs a shifted accumulator — is the encoding above.

Checked against real capture bytes (`services/world/replay/messages-redacted.txt`):

    type 0x15d   body[2:4] = 9d 05   -> (5 << 6) | 0x1d     = 349   = 0x15d
    type 0x1b88  body[2:4] = 88 6e   -> (0x6e << 6) | 0x08  = 7048  = 0x1b88
    type 0x663   body[2:4] = a3 19   -> (0x19 << 6) | 0x23  = 1635  = 0x663
    type 0x16a0  body[2:4] = a0 5a   -> (0x5a << 6) | 0x20  = 5792  = 0x16a0
    len  692     b4 0a               -> (0x0a << 6) | 0x34  = 692
    len  46393   d9 a9 05            -> (0x05a9 << 5) | 0x19 = 46393

Decoded against every server->client message in the capture, 137 of 138
message types round-trip exactly; the single exception is seq 0x25, which is
the first message of its datagram and carries a datagram-level preamble that
this module does not model (see bundle.py).

WHY THE CONTINUATION BYTES ARE LITTLE-ENDIAN, NOT BIG-ENDIAN
------------------------------------------------------------
Ghidra renders the 3-byte branch as a `CONCAT21(...) << 4`, which reads like a
big-endian assembly with a 4-bit shift. That is a decompiler artifact: the
observed 3-byte value `d9 a9 05` is 46393, which is only reachable as
`(0x05a9 << 5) | 25`. Under a big-endian reading the same bytes give 1384633,
which is larger than the 46407-byte message that contains them, so the
big-endian reading is falsified by the data. Trust the bytes.
"""

from __future__ import annotations

__all__ = ["MAX_VALUE", "decode", "encode", "decode_from", "size_of"]

# 4 continuation bytes = 35 usable bits.
MAX_VALUE = (1 << 35) - 1


class VarintError(ValueError):
    """A malformed prefix varint (truncated, or larger than 5 bytes)."""


def _continuation_count(first: int) -> int:
    """Number of continuation bytes implied by the leading 1-bits of ``first``."""
    n = 0
    mask = 0x80
    while first & mask:
        n += 1
        mask >>= 1
    return n


def decode(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode one prefix varint. Returns ``(value, next_offset)``."""
    if offset >= len(data):
        raise VarintError(f"varint at {offset}: out of data")
    first = data[offset]
    n = _continuation_count(first)
    end = offset + 1 + n
    if end > len(data):
        raise VarintError(
            f"varint at {offset}: first byte 0x{first:02x} needs {n} more "
            f"byte(s) but only {len(data) - offset - 1} remain"
        )
    if n == 0:
        return first, offset + 1
    shift = 7 - n
    cont = int.from_bytes(data[offset + 1 : end], "little")
    value = (cont << shift) | (first & ((1 << shift) - 1))
    return value, end


def decode_from(data: bytes, offset: int = 0) -> int:
    """Decode one prefix varint and return only its value."""
    return decode(data, offset)[0]


def size_of(value: int) -> int:
    """Encoded byte length of ``value``.

    Capacity is 7 + 7n bits for n continuation bytes (the leading byte keeps
    7 - n low bits and the n continuation bytes add 8n), so the thresholds are
    2^7, 2^14, 2^21, 2^28, 2^35.
    """
    if value < 0 or value > MAX_VALUE:
        raise VarintError(f"value {value} outside 0..{MAX_VALUE}")
    if value < 0x80:
        return 1
    for n in (1, 2, 3):
        if value < (1 << (7 + 7 * n)):
            return 1 + n
    return 5


def encode(value: int) -> bytes:
    """Encode ``value`` as a prefix varint."""
    if value < 0 or value > MAX_VALUE:
        raise VarintError(f"value {value} outside 0..{MAX_VALUE}")
    if value < 0x80:
        return bytes([value])
    n = size_of(value) - 1
    shift = 7 - n
    low = value & ((1 << shift) - 1)
    high = value >> shift
    # The leading byte's high n bits are 1s; its low `shift` bits are the low
    # bits of the value.
    leading = (((0xFF << (8 - n)) & 0xFF) | low)
    return bytes([leading]) + high.to_bytes(n, "little")
