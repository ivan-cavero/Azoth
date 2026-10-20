"""The client's channel-1 input stream: where the CLIENT says the player is.

WHY THIS MODULE EXISTS
=====================
Server authority over movement needs three things in order: the client's claim, a
plausibility check, and the server's own truth. This module is the first one — it reads
the position out of the record the client already streams ~20 times a second, so the
server stops guessing and starts comparing.

Everything below was derived from captured traffic, not from a decompiler guess. The
evidence is the world server's own traffic log (`.azoth/logs/world.log`,
`services/world/rep_traffic.jsonl`) from the 2026-10-14 sessions, and the numbers quoted
are reproducible with `scripts/alc-position.py`.

THE RECORD
==========
Channel 1 carries one typed message, wire type `0x635` (1589),
`ActionListComponentServerFacet_ReceiveInputFromClient`, addressed to the local player's
own actor id. Its container is the same `[crc32][len]` form as every other typed record:

    [u32 BE crc32][u32 BE len][16-byte target][00 01][prefix-varint type][body]

`target` is the 16-byte actor id (`1a954abc4b3185bfbe37c3d8592618e0` in the recorded
sessions), the marker is `00 01`, and the type varint is 2 bytes for `0x635`, so the body
starts at payload offset 28.

WHERE THE POSITION IS, AND WHY A FIXED OFFSET DOES NOT WORK
===========================================================
The position is two consecutive big-endian float32. It is NOT at a fixed offset: the body
is a variable-length sequence, so the block shifts as the payload grows. Measured across
213,202 captured channel-1 payloads, the block sits at body offset 103 in the dominant
311-byte form, but at 104, 105, 113 and 124 in others.

What IS stable is the four bytes that precede it: `3d 4c cc cd`, the float32 `0.05`,
followed by three more floats and then the pair. So the position is located by that
marker, at `marker + 12`.

Measured over the same 213,202 payloads:

* **190,716** carry exactly ONE marker, and all 190,716 yield a plausible world position.
* **0** carry more than one marker, so the locator is unambiguous.
* **14,665** carry NO marker. Those are the pre-spawn records.

THE LOAD SIGNAL
===============
The marker's presence is also the real "the player is in the world" signal, and it is
what a fixed grace period should be replaced with. At session start the payload is
**93 bytes** and grows `93 → 108 → 123 → 138 → 153 → 154`; the marker first appears when
the body crosses roughly 280 bytes (payload 308), at **t+8s to t+14s** after the first
channel-1 record in all 11 of the 12 recorded sessions that reached the world. The
twelfth never grew past 154 bytes and never produced a marker — a failed load, correctly
reported as "not ready" rather than as a desync.

A 60-second timer is therefore 4-7x more conservative than the client's own state, and it
is blind for the whole window in which the player is already controllable.

WHAT THIS MODULE DOES NOT DO
============================
It does not decide whether the claim is *correct*. The value here is not the same quantity
the client's own `nw_getPlayerPosition` accessor reports: measured against that accessor
while the player stood still, it differed by **2.04 u to 4.03 u**, and the offset varies
per session and even within one. That offset is a property of the instrument, not of the
player, and `azoth_world.movement` keeps it out of the desync path. See
`reference_offset_is_an_instrument_property_20261018`.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from . import varint

# The only typed message the client sends on channel 1, ~20x/s.
#
# 1589 = 0x635, decoded from the two-byte prefix varint `b5 18`. It is NOT 0xC35: the
# prefix varint splits `b5` as one continuation bit plus six low bits, so the value is
# (0x18 << 6) | 0x35 = 1589. A reader that assumed a plain LEB128 varint would get 3125 and
# then fail every record.
INPUT_STREAM_TYPE = 0x635

# Container layout, measured on every channel-1 record in the captured sessions.
CONTAINER_CRC = 0
CONTAINER_LENGTH = 4
CONTAINER_TARGET = 8
CONTAINER_MARKER = 24  # the two bytes `00 01`
CONTAINER_TYPE = 26  # the prefix varint starts here

# The four bytes `3d 4c cc cd` are the float32 `0.05`. Twelve bytes later come the two
# floats that track the player. See the module docstring for why the marker, not an
# offset, is the locator.
POSITION_MARKER = b"\x3d\x4c\xcc\xcd"
POSITION_MARKER_SKIP = 12
POSITION_SIZE = 8

# A plausible world coordinate. The recorded sessions sit near x 9340, y 2790; the bounds
# are deliberately wide (they only have to separate a real position from the filler that
# occupies these offsets before the body has grown) and deliberately not a guess about
# world size: they are the range in which the marker locator was validated.
POSITION_MIN = 0.0
POSITION_MAX = 65536.0


class AlcError(ValueError):
    """The payload is not a channel-1 input record this module understands."""


@dataclass(frozen=True)
class PositionClaim:
    """Where the client says the player is, and where in the body it said it.

    ``marker_offset`` is kept because it is the evidence: a caller that logs it can tell a
    genuine layout change from a value that merely stopped looking like a position.
    """

    x: float
    y: float
    marker_offset: int
    body_length: int

    def distance_to(self, x: float, y: float) -> float:
        """Planar distance to another position. The wire carries no height."""
        return ((self.x - x) ** 2 + (self.y - y) ** 2) ** 0.5


def _plausible(value: float) -> bool:
    return POSITION_MIN <= value <= POSITION_MAX


def split_container(payload: bytes) -> tuple[bytes, int, bytes]:
    """Split a channel-1 record into ``(target, type, body)``.

    Raises ``AlcError`` when the container does not have the measured shape, so a caller
    cannot mistake a different record for an input stream.
    """
    if len(payload) < CONTAINER_TYPE + 1:
        raise AlcError(f"payload too short for a container: {len(payload)} bytes")
    if payload[CONTAINER_MARKER:CONTAINER_MARKER + 2] != b"\x00\x01":
        raise AlcError(
            "no `00 01` marker at the measured offset; this is not a typed record"
        )
    try:
        # `decode` returns (value, NEXT OFFSET), not (value, width).
        type_id, body_offset = varint.decode(payload, CONTAINER_TYPE)
    except varint.VarintError as exc:
        raise AlcError(f"type varint at {CONTAINER_TYPE} is malformed: {exc}") from exc
    target = payload[CONTAINER_TARGET:CONTAINER_MARKER]
    body = payload[body_offset:]
    return target, type_id, body


def read_position(body: bytes) -> PositionClaim | None:
    """The position the client reported, or ``None`` when the body has not grown yet.

    ``None`` is the meaningful answer, not a failure: it is what a pre-spawn body looks
    like, and it is the load signal. An ambiguous body (two markers) also returns ``None``
    rather than picking one — a layout change must not be silently averaged into a
    position.
    """
    marker = body.find(POSITION_MARKER)
    if marker < 0:
        return None
    if body.find(POSITION_MARKER, marker + 1) >= 0:
        return None
    offset = marker + POSITION_MARKER_SKIP
    if offset + POSITION_SIZE > len(body):
        return None
    x, y = struct.unpack(">ff", body[offset:offset + POSITION_SIZE])
    if not (_plausible(x) and _plausible(y)):
        return None
    return PositionClaim(x=x, y=y, marker_offset=marker, body_length=len(body))


def read_claim(payload: bytes) -> PositionClaim | None:
    """Position from a whole channel-1 payload, or ``None``.

    A payload that is not an input record is not an error here: channel 1 also carries
    system records, and a caller decoding a live stream should skip them rather than stop.
    """
    try:
        _target, type_id, body = split_container(payload)
    except AlcError:
        return None
    if type_id != INPUT_STREAM_TYPE:
        return None
    return read_position(body)


def is_world_ready(payload: bytes) -> bool:
    """Whether the client has grown its input body to the form that carries a position.

    This is the load-finished signal: measured at t+8s..t+14s after the first channel-1
    record, against a 60 s timer that cannot see the difference. It says the player entity
    exists and is simulating. It does not say the player has finished loading the world.
    """
    return read_claim(payload) is not None


# THE MOVEMENT BLOCK, decoded 2026-10-18 from 34 distinct positions in one session (34/34 exact).
#
# The input body carries the client's own movement state as a run of big-endian float32, and the
# marker `3d 4c cc cd` (the float 0.05) sits immediately before it. Measured layout, offsets from
# the START OF THE BODY (body = payload - 28):
#
#     payload 119 = body 91:  marker 3d4ccccd (0.05)
#     123  float32  a      -2.93 .. +0.33   (varies with movement, meaning not yet established)
#     127  float32  b      -0.01 .. +0.18   (idem)
#     131  float32  x       world x, byte-exact against the position the claim reports
#     135  float32  y       world y, byte-exact
#     139  float32  (zero while walking; not z - the wire carries a 2D position)
#     143  float32  (zero)
#
# Verified on every distinct position in the session: `x` and `y` here equal the pair the position
# claim reports, to within 0.01 u, 34 of 34. So the client's input stream carries its own movement
# state twice - once as the position pair and once inside this block - and this is the block a
# server needs to predict with.
#
# WHAT `a` AND `b` ARE, decoded 2026-10-18 from 1008 measured displacements across six sessions:
#
#   `a` is the CAMERA YAW, in radians, wrapped to [-pi, pi]. Established by the distribution of
#   (movement heading - a) over 1008 displacements: 47.8% at a+90 deg, 24.4% at a+180, 11.8% at
#   a-90, 5.4% at a+0. That is the signature of WASD relative to a camera: strafe, back, strafe,
#   forward. A candidate "heading of travel" reading fits only 5% and is refuted.
#
#   `b` is the CAMERA PITCH, in radians. Same reasoning as `a`, applied to the second angle: it has
#   637 distinct values but changes only **770 times in 197810 samples** (mean run 256), exactly like
#   `a` (729 changes, run 271) - so it is held camera state, not per-sample movement data. Its range
#   is [-30.3 deg, +26.1 deg], which is a pitch, and **691 of the 808 angle changes are SIMULTANEOUS
#   in `a` and `b`** (turning the mouse diagonally), with 38 `a`-only and 79 `b`-only changes
#   (looking up/down moves the pitch alone). Correlations against speed, forward speed and lateral
#   speed are all under 0.10, which is what an independent camera angle looks like.
#
# So the block is (pitch, yaw, x, y) - the client's camera orientation and its world position in one
# sample. That is everything a server needs to interpret a movement intent in the player's frame.
MOVEMENT_MARKER = b"\x3d\x4c\xcc\xcd"
MOVEMENT_BLOCK_OFFSET = 119          # in the PAYLOAD
MOVEMENT_BLOCK_BODY_OFFSET = 91      # the same block in the BODY (payload - 28)
MOVEMENT_BLOCK_SIZE = 28
MOVEMENT_A_OFFSET = 4
MOVEMENT_B_OFFSET = 8
MOVEMENT_X_OFFSET = 12
MOVEMENT_Y_OFFSET = 16
CAMERA_YAW_OFFSET = MOVEMENT_A_OFFSET


@dataclass(frozen=True)
class MovementState:
    """The client's own movement state, read from its input stream.

    ``a`` and ``b`` are raw and unnamed on purpose: they vary with movement but nothing has
    established what they mean, and inventing a meaning is how this project has wasted sessions.
    """

    x: float
    y: float
    a: float
    b: float
    marker_offset: int

    def position(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def camera_yaw(self) -> float:
        """The camera yaw in radians, wrapped to [-pi, pi].

        MEASURED 2026-10-18: 1008 displacements classify as strafe/back/strafe/forward relative to
        this angle (47.8% at +90 deg, 24.4% at +180, 11.8% at -90, 5.4% at 0), which is what WASD
        movement looks like against a camera yaw. The competing reading, "direction of travel",
        fits 5% and is refuted.
        """
        return self.a

    @property
    def camera_yaw_degrees(self) -> float:
        return math.degrees(self.a)

    @property
    def camera_pitch(self) -> float:
        """The camera pitch in radians.

        MEASURED 2026-10-18: `b` changes only 770 times in 197810 samples (held camera state, like
        the yaw's 729), spans [-30.3 deg, +26.1 deg] (a pitch range), and 691 of the 808 angle
        changes are simultaneous with the yaw (turning the mouse diagonally) while 79 are
        pitch-only (looking up or down).
        """
        return self.b

    @property
    def camera_pitch_degrees(self) -> float:
        return math.degrees(self.b)


def read_movement_state(body: bytes) -> MovementState | None:
    """The movement block, or ``None`` when the body does not carry one.

    ``None`` is the pre-spawn answer, same as `read_position`: a body that has not grown yet has no
    marker and therefore no movement state.
    """
    marker = body.find(MOVEMENT_MARKER)
    if marker < 0:
        return None
    if body.find(MOVEMENT_MARKER, marker + 1) >= 0:
        return None
    base = marker + 4
    if base + MOVEMENT_BLOCK_SIZE - 4 > len(body):
        return None
    try:
        a, b, x, y = struct.unpack_from(">ffff", body, base)
    except struct.error:
        return None
    if not (_plausible(x) and _plausible(y)):
        return None
    return MovementState(x=x, y=y, a=a, b=b, marker_offset=marker)


def read_movement_from_payload(payload: bytes) -> MovementState | None:
    """Movement state from a whole channel-1 payload, or ``None``."""
    try:
        _target, type_id, body = split_container(payload)
    except AlcError:
        return None
    if type_id != INPUT_STREAM_TYPE:
        return None
    return read_movement_state(body)


# THE MOVEMENT BUFFER, decoded 2026-10-18 and this is the live position feed.
#
# WHY THIS WAS MISSED FOR SO LONG, and the mistake is worth recording: the idle body is **311 bytes**
# and carries ONE position - the spawn anchor, which never moves. Everything in this project filtered
# for `len(payload) == 311`, so the anchor was all it ever saw, and it concluded the channel carries no
# live position. IT DOES. When the player moves the body GROWS (403-412 bytes) and carries a
# **sliding buffer of the most recent movement samples**, newest first.
#
# MEASURED: 5 entries per message at 20 Hz (0.051 s apart), traced against the client's own position
# accessor polled at 20 Hz during a real 23 u walk. With the frame offset applied, every entry lands
# on the accessor's trajectory with **d = 0.000 u**, entry by entry, message after message. The
# buffer's last entry is the anchor while the buffer is still filling, which is how the two forms
# were tied together.
#
# THE FRAME OFFSET. The positions on the wire are offset from what the accessor reports by a constant
# (-2.2002, +3.3777) - the same "instrument offset" measured earlier and the same one the anchor has.
# It is a frame difference between the two quantities, not noise, and it is why comparing them
# directly produced a constant 4.0311 u.
#
# LAYOUT. Entries are ~63 bytes apart, each `[f32be x][f32be y]` followed by a trailer whose last
# byte before the next entry is a descending input sequence number. The first entry follows the
# 0.05 marker by 12 bytes, exactly like the single anchor does in the idle form - the two forms share
# the same head and differ only in how many entries follow.
MOVEMENT_BUFFER_MIN_GAP = 50
MOVEMENT_BUFFER_MAX_STEP = 20.0
"""Consecutive entries must be within this many units: it is a movement buffer, not a position dump."""


def read_movement_buffer(body: bytes) -> tuple[tuple[float, float], ...]:
    """Every movement sample in the body, NEWEST FIRST. Empty when the body has none.

    The idle form returns a single entry (the anchor). The moving form returns up to five, newest
    first, each 0.051 s apart. A caller that wants the live position wants ``[0]``; a caller that
    wants history has the rest.

    ANCHORED ON THE MARKER, not on a free scan. A free scan for plausible floats is wrong here: the
    filler in this body is full of small values like 0.00 and 2.50 that pass a wide plausibility test,
    and the first such false hit blocks every real entry behind the minimum-gap rule (measured: a
    free scan returned 1 entry for a body that carries 5). So the walk starts at the marker's own
    offset + 12 - the same position the single anchor occupies in the idle form - and each further
    entry is searched for in a narrow window after the previous one.
    """
    marker = body.find(MOVEMENT_MARKER)
    if marker < 0:
        return ()
    if body.find(MOVEMENT_MARKER, marker + 1) >= 0:
        return ()
    first = marker + 12
    if first + 8 > len(body):
        return ()
    x, y = struct.unpack_from(">ff", body, first)
    if not (_plausible(x) and _plausible(y)):
        return ()
    entries: list[tuple[float, float]] = [(x, y)]
    cursor = first
    while True:
        px, py = entries[-1]
        found = None
        for offset in range(cursor + MOVEMENT_BUFFER_MIN_GAP, min(cursor + 80, len(body) - 7)):
            cx, cy = struct.unpack_from(">ff", body, offset)
            if not (_plausible(cx) and _plausible(cy)):
                continue
            # A movement buffer's entries are consecutive samples: close together in space.
            if ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 > MOVEMENT_BUFFER_MAX_STEP:
                continue
            found = (offset, cx, cy)
            break
        if found is None:
            return tuple(entries)
        cursor = found[0]
        entries.append((found[1], found[2]))


def read_movement_buffer_from_payload(payload: bytes) -> tuple[tuple[float, float], ...]:
    """Movement buffer from a whole channel-1 payload. Empty when it is not an input record."""
    try:
        _target, type_id, body = split_container(payload)
    except AlcError:
        return ()
    if type_id != INPUT_STREAM_TYPE:
        return ()
    return read_movement_buffer(body)


# THE FRAME OFFSET between the wire position and the client's own accessor.
#
# MEASURED 2026-10-18: `wire = accessor + MOVEMENT_FRAME_OFFSET`, constant to 0.000 u. It is the same
# offset the spawn anchor has, which is how the two forms were tied together. It is a FRAME difference
# between two quantities the client computes (the wire value and what `nw_getPlayerPosition` prints),
# not noise - which is why comparing them directly produced a constant 4.0311 u and made an in-sync
# player look permanently desynced.
#
# THE SERVER STAYS IN THE WIRE FRAME. The anchor is in that frame, the buffer is in that frame, and
# the state the server writes back is in that frame, so no conversion is needed for authority. The
# constant exists only for comparing against the accessor, which is a client-side instrument.
MOVEMENT_FRAME_OFFSET = (-2.2002, 3.3777)


def read_live_position(payload: bytes) -> tuple[float, float] | None:
    """The player's CURRENT position from the channel-1 body, or ``None``.

    This is the newest entry of the movement buffer, which is the value that actually follows the
    player. Prefer it over `read_claim`: the claim reads the anchor, which only changes on teleport
    or respawn (measured - it stayed fixed through a 23 u walk while this moved).
    """
    buffer = read_movement_buffer_from_payload(payload)
    return buffer[0] if buffer else None


def to_accessor_frame(position: tuple[float, float]) -> tuple[float, float]:
    """Convert a wire position into what the client's own accessor would report."""
    return (position[0] - MOVEMENT_FRAME_OFFSET[0], position[1] - MOVEMENT_FRAME_OFFSET[1])
