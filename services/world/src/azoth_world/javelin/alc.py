"""The client's channel-1 ALC input stream (wire type 0x635).

WHY THIS MODULE EXISTS
=====================
The client sends ONE message type on channel 1 about 20 times a second, and it is the
missing half of the movement contract: ALC ("Actor Local Control") is the scheme where the
client sends INPUT, the server COMBINES it and answers with authoritative position. Until
this module the server could not read that stream at all — it only stored the raw body for
an echo experiment.

MEASURED 2026-10-16, and this is the finding that makes the stream useful: **the body
carries the client's own world position as two big-endian float32 values**, and the value
tracks the position the client's own accessor reports (`FUN_140fddfa0`, the instrument
`nw_getPlayerPosition` uses).

THE LAYOUT, and how it was established
--------------------------------------
The container is the standard typed record
`[u32 BE crc32][u32 BE len][16-byte target][00 01][prefix-varint type][body]`, so the body
begins at offset 28 for this type (the record's target is the full 16-byte actor id). The
BODY then begins with another 16-byte local id — the server facet the client is calling,
`fbde4b9a600d428fbf85314bbc4a951a` in the sessions measured, the same value family the
capture's input-response target uses — followed by a header and a variable number of
buffered input entries. The entry grammar is NOT decoded, and this module deliberately does
not pretend otherwise.

What IS decoded, and why it is safe:

* every body that carries a position contains the 4-byte constant `3d 4c cc cd` (= 0.05f,
  which matches the client's own `javelin.alc-interpolation.normal-movement-quantization`)
  **exactly once** — measured over 6 000 live bodies, the count was 1..1 for every length
  that had one at all, and 0 for the short forms;
* the position pair is **always 12 bytes after that anchor**, in 100% of the bodies measured
  (4 685 of the 257-byte form and every larger form);
* the pair is written big-endian, like every other float on this wire.

So the extractor is anchored on a structural constant and then validated by RANGE, and it
returns nothing rather than a guess when either check fails. Bodies with no anchor are the
short forms (measured 65-126 bytes in one session, 39-100 in another) and carry no position.

WHAT THE VALUE IS NOT
---------------------
It is not byte-identical to the accessor's value: measured against the accessor over a live
walk, the streamed position sits at a **constant offset of about 2.2 u** (the two are
different reference points on the character), and during movement it trails by roughly
another unit. Removing that offset leaves a median residual of **0.54 u standing still and
0.81 u while walking**, which is the accuracy an authoritative check can work with.

It is also NOT the position the server sent: in the run that measured it the server's
spawn value was `(9343.6416, 2786.7327)` and the client streamed `(9341.984, 2790.342)`
while standing, then followed the player as it walked. So this is the client's own live
position, which is what makes it usable as a movement-validation input.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import varint

__all__ = [
    "TYPE_ALC_INPUT",
    "QUANTIZATION",
    "QUANTIZATION_ANCHOR",
    "POSITION_OFFSET_FROM_ANCHOR",
    "X_RANGE",
    "Y_RANGE",
    "AlcInput",
    "alc_body_from_record",
    "parse_alc_input",
]

# The client's local-player input/state stream. Named
# `ActionListComponentServerFacet_ReceiveInputFromClient` in the wire registry (index
# 1589), and the only type the client ever sends on channel 1.
TYPE_ALC_INPUT = 0x635

# The anchor: a float32 0.05, matching `javelin.alc-interpolation.normal-movement-quantization`.
QUANTIZATION = 0.05
QUANTIZATION_ANCHOR = struct.pack(">f", QUANTIZATION)
# The position pair begins this many bytes after the anchor.
POSITION_OFFSET_FROM_ANCHOR = 12

# The world this build's capture lives in. A pair outside these bounds is not a position, so
# the range check is what keeps a coincidental anchor from producing a plausible-looking lie.
X_RANGE = (8000.0, 11000.0)
Y_RANGE = (1500.0, 3500.0)

# Container: `[u32 BE crc32][u32 BE len][16-byte target][00 01][varint type]`.
_TARGET_OFFSET = 8
_TARGET_LEN = 16
_TYPE_MARKER_OFFSET = _TARGET_OFFSET + _TARGET_LEN  # 24
_BODY_OFFSET = _TYPE_MARKER_OFFSET + 2  # 26, where the type varint starts


@dataclass(frozen=True)
class AlcInput:
    """One channel-1 ALC body, reduced to the field that is decoded.

    `position` is ``None`` for the short bodies that carry no anchor; `anchor_offset` and
    `body_length` are kept because the body length changes with the number of buffered
    inputs (a measured 257-259 bytes with four entries, 68 with one) and a caller may want
    to watch that without decoding the entries.
    """

    position: tuple[float, float] | None
    anchor_offset: int
    body_length: int


def alc_body_from_record(payload: bytes) -> bytes | None:
    """Strip the container from a channel-1 record payload, or None if it is not one.

    Returns None rather than raising: this runs inside the datagram loop, where a malformed
    record must not take the peer down (that exact failure mode cost a session on
    2026-10-11, see `on_app_data`).
    """
    if len(payload) < _BODY_OFFSET + 1:
        return None
    if payload[_TYPE_MARKER_OFFSET:_TYPE_MARKER_OFFSET + 2] != b"\x00\x01":
        return None
    try:
        type_id, after = varint.decode(payload, _BODY_OFFSET)
    except varint.VarintError:
        return None
    if type_id != TYPE_ALC_INPUT:
        return None
    return payload[after:]


def parse_alc_input(body: bytes) -> AlcInput:
    """Extract the client's reported position from one ALC body.

    Fails closed: a body whose anchor is missing, or whose pair is outside the world's
    bounds, reports ``position=None`` instead of a value a caller might act on.
    """
    anchor = body.find(QUANTIZATION_ANCHOR)
    if anchor < 0:
        return AlcInput(position=None, anchor_offset=-1, body_length=len(body))
    at = anchor + POSITION_OFFSET_FROM_ANCHOR
    if at + 8 > len(body):
        return AlcInput(position=None, anchor_offset=anchor, body_length=len(body))
    x, y = struct.unpack(">ff", body[at:at + 8])
    if not (X_RANGE[0] < x < X_RANGE[1] and Y_RANGE[0] < y < Y_RANGE[1]):
        return AlcInput(position=None, anchor_offset=anchor, body_length=len(body))
    return AlcInput(position=(x, y), anchor_offset=anchor, body_length=len(body))
