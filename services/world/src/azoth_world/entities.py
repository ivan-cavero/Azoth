"""Server-side entities: the server decides where an entity is, and the client renders it.

WHY THIS MODULE EXISTS
=====================
Until now every record in the state stream was a captured body forwarded verbatim, except the local
player's own. The server could follow the player but could not put anything of its OWN into the world.
This module is the first place the server owns an entity's state and writes it.

THE TEMPLATE, AND WHY IT IS A CAPTURED RECORD
=============================================
An entity record has to be a shape the client already parses: the record id selects a handler
(`state + 0x608 + record_id*0x10`), and the fragments' type indices select per-component codecs that
this project has not decoded. Composing an entity from scratch would mean inventing all of that.

So the server starts from a **captured** entity record and changes only its position. That is the
same method that produced the first authoritative effect for the player (2026-10-14, 0.0000 u), and
it keeps every undecoded byte exactly as the client expects.

MEASURED TEMPLATE, record 70 (replay seq 0xb0)
=============================================
* `record_id 70`, **2 fragments**, payload **162 bytes**
* the world position appears **twice**, at payload offsets **6** and **74**, as the same
  big-endian float32 pair - measured byte-identical, so it is one value stored twice
* seq `0xb0` is at or above `STATE_STREAM_MIN_SEQ` (0x94), so the stream **already re-sends this
  record** every cycle: the client is already receiving it, and changing the bytes it carries is a
  one-variable change rather than a new message

THE POSITION IS ANCHORED ON THE CAPTURED VALUE
==============================================
`replace_position` rewrites the pair only where the CAPTURED value still sits, so it fires only in a
body that actually carries this entity's position and cannot corrupt a body that does not. Both
occurrences are rewritten together, because a body where only one of them moved would be a body the
client never produces.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .javelin import bundle as javelin_bundle


@dataclass(frozen=True)
class EntityTemplate:
    """A captured entity record the server can drive.

    ``position_offsets`` are payload offsets where the captured position pair sits. They are
    recorded rather than searched for at send time because the search is anchored on the captured
    VALUE, which stops matching as soon as the server has written its own position.
    """

    record_id: int
    captured_position: tuple[float, float]
    position_offsets: tuple[int, ...]
    payload_length: int

    def captured_bytes(self) -> bytes:
        return struct.pack(">ff", *self.captured_position)


def template_from_replay(seq: int) -> EntityTemplate | None:
    """Build a template from a captured bundle, so any captured entity can be driven.

    The position is taken at payload offset 6, which is where every entity record measured on
    2026-10-19 carries it (records 82, 80, 78, 77, 76, 24, 85, 70 - all of them), and the number of
    occurrences of that exact pair is recorded so the rewrite can refuse a body whose layout differs.

    Returns ``None`` when the body is not a decodable bundle with a plausible position there.
    """
    from .javelin.replay_store import ReplayStore

    store = ReplayStore(str(_REPLAY_PATH))
    for message in store.messages:
        if message.seq != seq or message.direction != "R":
            continue
        try:
            payload = javelin_bundle.decode_bundle(message.body).payload
        except javelin_bundle.BundleError:
            return None
        if len(payload) < 14:
            return None
        # THE POSITION IS NOT AT A FIXED OFFSET. Measured 2026-10-19: entity records carry it at
        # payload offset 6 (records 82/80/78/77/76/24/85/70) and at 238 (record 29). So it is found by
        # VALUE - the first plausible world coordinate in the payload - and the number of times that
        # exact pair occurs is recorded, which is what lets the rewrite refuse a body whose layout
        # differs.
        position = None
        for offset in range(0, len(payload) - 7):
            x, y = struct.unpack_from(">ff", payload, offset)
            if 5000.0 < x < 15000.0 and 500.0 < y < 8000.0:
                position = (x, y)
                break
        if position is None:
            return None
        x, y = position
        pair = struct.pack(">ff", x, y)
        offsets = []
        index = payload.find(pair)
        while index >= 0:
            offsets.append(index)
            index = payload.find(pair, index + 1)
        return EntityTemplate(
            record_id=payload[0],
            captured_position=(x, y),
            position_offsets=tuple(offsets),
            payload_length=len(payload),
        )
    return None


_REPLAY_PATH = Path(__file__).resolve().parents[2] / "replay" / "messages-redacted.txt"


# MEASURED 2026-10-19 from the committed replay, decoded with the repo's own `decode_bundle`.
# Record 70 carries the pair TWICE (offsets 6 and 74); the larger entity records carry it once.
# `template_from_replay` derives either shape, and this constant keeps the measured one named.
RECORD_70 = EntityTemplate(
    record_id=70,
    captured_position=(9375.5410, 2655.7583),
    position_offsets=(6, 74),
    payload_length=162,
)


def replace_position(
    body: bytes, template: EntityTemplate, position: tuple[float, float]
) -> tuple[bytes, int]:
    """Rewrite the entity's position in a bundle body.

    Returns ``(body, replacements)``. Zero replacements means the body is not this entity's, so the
    caller forwards it unchanged rather than guessing.

    The replacement is the same width as what it replaces, so the payload length does not change, and
    the body is re-encoded through the verified parser rather than patched in place - a raw byte write
    is what produced a measured `ValidationError` when a counter widened.
    """
    try:
        parsed = javelin_bundle.decode_bundle(body)
    except javelin_bundle.BundleError:
        return body, 0
    payload = parsed.payload
    if len(payload) != template.payload_length:
        return body, 0
    if payload[0] != template.record_id:
        return body, 0

    captured = template.captured_bytes()
    replacement = struct.pack(">ff", *position)
    if payload.count(captured) != len(template.position_offsets):
        # The capture's value is not where it was measured: the layout changed, so do not write.
        return body, 0

    patched = payload.replace(captured, replacement)
    return javelin_bundle.encode_bundle(parsed.replication_seq, patched), payload.count(captured)


def replace_entity_position(
    body: bytes, captured: tuple[float, float], position: tuple[float, float]
) -> tuple[bytes, int]:
    """Rewrite an entity's position ANYWHERE it appears in a bundle body, by VALUE.

    WHY BY VALUE AND NOT BY RECORD. Measured 2026-10-19: one entity's position is carried by TWO
    different records - record 68 (replay seq 0x7a) CREATES the entity and carries the pair at
    payload offsets 159 and 227, and record 70 (seq 0xb0) UPDATES it and carries the same pair at
    offsets 6 and 74. The creation record sits BELOW the state stream's floor, so the replay sends it
    once and the stream never does; patching only the update record therefore moves an entity that
    was already created at the capture's position.

    Anchoring on the captured VALUE covers both records with one rule, and it is the same method that
    produced the first authoritative effect for the player (2026-10-14, 0.0000 u). It also cannot
    corrupt a body that does not carry this entity's position.

    Returns ``(body, replacements)``; zero means this body is not about this entity.
    """
    try:
        parsed = javelin_bundle.decode_bundle(body)
    except javelin_bundle.BundleError:
        return body, 0
    captured_bytes = struct.pack(">ff", *captured)
    count = parsed.payload.count(captured_bytes)
    if not count:
        return body, 0
    patched = parsed.payload.replace(captured_bytes, struct.pack(">ff", *position))
    return javelin_bundle.encode_bundle(parsed.replication_seq, patched), count


def parse_position(raw: str) -> tuple[float, float] | None:
    """Parse ``x,y`` into a position, or None. A typo must not move an entity somewhere absurd."""
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    if len(parts) != 2:
        return None
    try:
        x, y = (float(p) for p in parts)
    except ValueError:
        return None
    if not (-100000.0 < x < 100000.0 and -100000.0 < y < 100000.0):
        return None
    return (x, y)


# DUPLICATING A CAPTURED ENTITY UNDER A NEW SLOT.
#
# MEASURED 2026-10-19, and it is the key to creating an entity rather than moving one. The client's
# record dispatcher (`FUN_141717fc0`) looks up `state + 0x608 + record_id*0x10` and:
#
#   * slot EMPTY   -> CREATION: it builds the entity and applies the whole record in one call;
#   * slot PRESENT -> UPDATE: it applies only when `byte[msg+8]` is zero, otherwise skips silently.
#
# So a record id that the capture never used is a CREATION slot. Sending a captured entity record
# under such an id makes the client build a second entity from the same fragments - the same body the
# client already parses, with a different handler index.
#
# WHY THE WHOLE BODY IS REUSED RATHER THAN REBUILT: a fragment carries no length field, its payload
# length is implied by its type, and only `key=16 type=11` has been decoded. Composing a character
# from fragments would mean inventing the other 18 codecs. Copying the body keeps every undecoded byte
# exactly as the client produced it, and changing only the record id and the position is a
# one-variable change.

# THE RECORD IDS THE CLIENT'S OWN SLOT TABLE HAS OCCUPIED, measured live 2026-10-19.
#
# WHY THIS REPLACES THE CAPTURE-DERIVED SET. The first version of this module derived the occupied
# ids from the capture and treated anything outside it as a creation slot. That set is a LOWER
# BOUND and it is wrong: a bundle payload is a SEQUENCE of records (`[u8 id][u8 frags]
# [fragments...]`, repeated), and the derivation only read the FIRST record of each payload because
# the fragment payloads carry no length field, so the walk cannot advance. The consequence was
# MEASURED, not theorised: slot 3 was chosen, and the client's own dispatcher reported
# `slotEmpty: false` for it on every send - i.e. the message was an UPDATE to an entity that already
# existed, discarded by the first-write-wins component maps, so no second body appeared.
#
# The authoritative answer comes from the client: `state + 0x608 + record_id*0x10` for every id.
# Measured with `reverse/probes/client/frida-record-slots.py` on a live world: **ids 1..94 are all
# occupied and 95..255 are all NULL** - a contiguous range, which is what a handler table allocated
# once at world load looks like.
MEASURED_USED_SLOTS = frozenset(range(1, 95))

# Kept for the record: the ids the capture's FIRST record of each payload used. It is a lower bound
# and must NOT be used to decide whether a slot is free - see MEASURED_USED_SLOTS.
CAPTURED_RECORD_IDS = frozenset(
    {1, 2, 10, 22, 24, 29, 30, 35, 38, 39, 44, 58, 60, 66, 68, 70, 72,
     75, 76, 77, 78, 79, 80, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94}
)


def free_record_ids() -> list[int]:
    """Record ids the client's slot table has NOT allocated, i.e. real creation slots, ascending.

    Uses the MEASURED table, not the capture-derived lower bound: the capture's first-record scan
    misses every record that is not first in its payload, and choosing from it produced a slot that
    was already occupied.
    """
    return [i for i in range(1, 256) if i not in MEASURED_USED_SLOTS]


def duplicate_entity(
    body: bytes,
    *,
    record_id: int,
    position: tuple[float, float] | None = None,
    captured_position: tuple[float, float] | None = None,
) -> tuple[bytes, dict]:
    """Re-emit a captured entity record under a NEW record id, optionally at a new position.

    ``record_id`` must be a creation slot (see `free_record_ids`); using an id the capture already
    uses turns the message into an update, which the client applies only conditionally.

    Returns ``(body, report)``. The report carries ``record_id``, ``fragments`` and, when a position
    was supplied, ``replacements``. A body that is not a decodable bundle is returned unchanged with
    ``error`` set, so a caller cannot send a guess.
    """
    report: dict = {"record_id": record_id, "fragments": 0, "replacements": 0}
    try:
        parsed = javelin_bundle.decode_bundle(body)
    except javelin_bundle.BundleError as exc:
        report["error"] = str(exc)[:120]
        return body, report
    payload = parsed.payload
    if len(payload) < 2:
        report["error"] = "payload too short for a record header"
        return body, report
    if record_id in MEASURED_USED_SLOTS:
        report["error"] = (
            f"record id {record_id} is already allocated in the client's slot table "
            f"(an update, which the first-write-wins component maps discard)"
        )
        return body, report

    patched = bytearray(payload)
    patched[0] = record_id
    report["fragments"] = payload[1]

    if position is not None and captured_position is not None:
        captured = struct.pack(">ff", *captured_position)
        count = bytes(patched).count(captured)
        if count:
            patched = bytearray(bytes(patched).replace(captured, struct.pack(">ff", *position)))
            report["replacements"] = count
        else:
            report["error"] = "the captured position is not in this body"
            return body, report

    return javelin_bundle.encode_bundle(parsed.replication_seq, bytes(patched)), report

# ---------------------------------------------------------------------------------------------
# CREATING AN ACTOR: THE ENTITY DECLARES ITS OWN ACTOR ID
# ---------------------------------------------------------------------------------------------
#
# MEASURED 2026-10-19, and it is what makes "a NEW actor" possible without inventing a single
# undecoded byte. An entity record does NOT just carry component state: it carries its own
# instance of the entity's slice, and that instance carries the record's actor id.
#
# In record 29 (replay seq 0xa1, a character, 19 fragments, 994-byte payload) the slice instance
# sits at payload offset 642 and reads
#
#     00 0a 01 03 | A660EEEB-EBC7-5CB7-BE6B-AB11EB831731 | 00 00 00 02 | <16-byte actor id>
#     key=0 type=10         slices/remoteplayer.dynamicslice      tag        3c757da5b254…
#
# and the SAME shape appears in the 48-fragment spawn record at payload offset 29707 (fragment #22),
# where the trailing 16 bytes are the LOCAL PLAYER's actor id `1a954abc4b3185bfbe37c3d8592618e0`.
# That is why `ClientAddEntryMsg` is sent twice for the player before the spawn: the actor has to be
# registered before a record can bind component state to it.
#
# So creating an entity is two steps, and both are byte-exact copies of what the client already
# parses:
#
#     1. `client_add_entry(actor_id)` - the 20-byte `[00 01][a4][16-byte actor id]` registration;
#     2. `duplicate_entity(..., actor_id=...)` - the captured record under a free record id, with its
#        slice instance pointing at the NEW actor id.
#
# Changing the actor id in place is safe in a way that composing a character is not: the id is a
# fixed-width 16-byte field whose value the server legitimately owns, and everything else in the
# record - the 19 fragments, their keys, their type indices and every undecoded payload byte - stays
# exactly as the client produced it.
ENTITY_SLICE_GUID = bytes.fromhex("a660eeebebc75cb7be6bab11eb831731")  # slices/remoteplayer.dynamicslice
# The four bytes between the slice GUID and the actor id. Measured on both records that carry the
# shape; asserted rather than skipped so a layout change cannot silently rewrite the wrong field.
SLICE_INSTANCE_TAG = b"\x00\x00\x00\x02"
ACTOR_ID_SIZE = 16
CLIENT_ADD_ENTRY_TYPE = 0xA4

def client_add_entry(actor_id: bytes) -> bytes:
    """The `ClientAddEntryMsg` body that registers one actor: `[00 01][a4][16-byte actor id]`.

    MEASURED: wire type 0xa4, 20 bytes, sent twice for the local player before the spawn (replay
    seq 0x08 and 0x0f, byte-identical). Registering an actor is the step that has to happen BEFORE a
    record can carry that actor's component state, so a new entity needs this message and not only a
    record.
    """
    if len(actor_id) != ACTOR_ID_SIZE:
        raise ValueError(f"an actor id is {ACTOR_ID_SIZE} bytes, got {len(actor_id)}")
    return javelin_bundle.encode_type_marker(CLIENT_ADD_ENTRY_TYPE) + actor_id

def slice_actor_ids(payload: bytes) -> list[tuple[int, bytes]]:
    """Every `(offset, actor id)` where this payload declares an entity's actor id.

    Anchored on the slice GUID and then on the measured tag, so a body whose layout differs returns
    an empty list rather than a wrong offset.
    """
    found: list[tuple[int, bytes]] = []
    index = payload.find(ENTITY_SLICE_GUID)
    while index >= 0:
        actor_at = index + len(ENTITY_SLICE_GUID) + len(SLICE_INSTANCE_TAG)
        if payload[index + len(ENTITY_SLICE_GUID) : actor_at] != SLICE_INSTANCE_TAG:
            index = payload.find(ENTITY_SLICE_GUID, index + 1)
            continue
        if actor_at + ACTOR_ID_SIZE > len(payload):
            break
        found.append((actor_at, payload[actor_at : actor_at + ACTOR_ID_SIZE]))
        index = payload.find(ENTITY_SLICE_GUID, actor_at + ACTOR_ID_SIZE)
    return found

def rewrite_actor_id(body: bytes, actor_id: bytes) -> tuple[bytes, dict]:
    """Point a captured entity record at a DIFFERENT actor id.

    Returns ``(body, report)``; on any doubt the original body is returned with ``error`` set, so a
    caller can never send a guess. ``report["previous"]`` lists the actor ids that were replaced,
    which is what lets a live run prove it rewrote the intended field and not a neighbour.
    """
    report: dict = {"replacements": 0, "previous": []}
    if len(actor_id) != ACTOR_ID_SIZE:
        report["error"] = f"an actor id is {ACTOR_ID_SIZE} bytes, got {len(actor_id)}"
        return body, report
    try:
        parsed = javelin_bundle.decode_bundle(body)
    except javelin_bundle.BundleError as exc:
        report["error"] = str(exc)[:120]
        return body, report
    payload = parsed.payload
    found = slice_actor_ids(payload)
    if not found:
        report["error"] = "no slice instance in this record (no actor id to rewrite)"
        return body, report
    if any(current == actor_id for _, current in found):
        report["error"] = "this record already declares that actor id"
        return body, report
    patched = bytearray(payload)
    for offset, current in found:
        patched[offset : offset + ACTOR_ID_SIZE] = actor_id
        report["previous"].append(current.hex())
    report["replacements"] = len(found)
    return javelin_bundle.encode_bundle(parsed.replication_seq, bytes(patched)), report
