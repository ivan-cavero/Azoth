"""The Javelin type-0x08 StateBundle: the entity/component replication record.

WHY THIS MODULE EXISTS
=====================
This is the message that carries world and entity state to the client — every
replica, every component, the local player's own metadata. Understanding it is
the prerequisite for server-authoritative entities (NPCs) and for the local
player's physics. Until this session the server could only replay captured bytes;
it could not read or build one.

THE VERIFIED LAYOUT (build 8654f01d…)
------------------------------------
    [00 01 <varint 0x08>]      typed marker
    [8-byte prologue]          offsets 3..10: `01 <varint SEQ> 01 01 01 01 00 00`
                               The six bytes after the seq varint are INVARIANT
                               across all 78 captured bundles.
    [varint payload_length]
    [payload]                  a SEQUENCE OF RECORDS, each:
                                   [u8 record_id][u8 fragment_count][fragments…]

`SEQ` is the replication counter the client's unreliable-replication gate
compares against its high-water (see below).

HOW THIS WAS ESTABLISHED, AND WHY THE PREVIOUS MODEL WAS WRONG
-------------------------------------------------------------
The earlier model read the prologue's bytes as `[kind][record_id][fragment_count]`
and then treated the whole length-prefixed payload as ONE fragment's payload.
That model consumed every captured body exactly — which is why it looked right —
but **"consumes exactly" cannot discriminate** when the remainder is opaque.

The discriminating evidence is the client's own behaviour, measured live with a
Frida probe on `FUN_146af20d0` (one record) and `FUN_146af2340` (one fragment):

* For each record the probe measured the bytes consumed and the number of nested
  `FUN_146af2340` calls. The record's `fragment_count` byte **equals the measured
  nested-call count in every one of 90 distinct records**:
  `01 30`→48, `01 09`→9, `02 03`→3, `03 01`→1, `0d 06`→6, `1d 13`→19.
* Byte-exact on the 78-byte bundle (capture seq 0xab): its payload length is 66
  and the payload is **two records of exactly 33 bytes** each (`48 03 …` and
  `49 03 …`); 33+33 = 66, and the client measured `consumed=33, fragments=3` for
  each.
* `record_id` values are **sequential** across a session (1, 2, 3, …, 0x2e, then
  0x48, 0x49, 0x4a) — what a handler index looks like, and `FUN_141717fc0`
  indexes exactly that at `state + 0x608 + record_id*0x10`.

So the real `fragment_count` for the spawn record is **48**, not 1.

THE FRAGMENT GRAMMAR (also verified, 2026-10-10)
----------------------------------------------
A fragment is:

    [varint KEY][varint TYPE_INDEX][type-specific payload]

The header is **exactly two varints and there is no length field**. Measured with
a live Frida probe that hooks the shared varint reader plus both readers and
logs, per fragment, every varint read and its offset from the fragment start:
across **300 fragments the first two varints sit at offset 0 and 1 in every single
one**, with zero exceptions; further varints begin at offset 5 or later and are
payload-internal. 48 distinct keys, 47 distinct types, and the key→type binding
is **1:1** (no key ever maps to two types). The keys are sparse
(0,1,2,4,5,9,10,12,13,14,16,19,20,22,27,29,31,…,77), which is what a component
slot table with freed slots looks like — and the spawn record carries exactly 48
fragments with exactly 48 distinct keys.

Because no length is stored, the payload length is **implied by the type**: the
reader consumes it through the type object's vtable `+0x90`, so each type's
reader knows its own length.

STILL OPEN
----------
1. The meaning of `SEQ` beyond "the gate counter" (1..34 across the capture).
2. The **per-type payload encoding** — one codec per component type. The container
   is now understood down to the fragment; this is the remaining long tail, and it
   is also what physics needs, since a physics component would arrive as one of
   these fragments.

THE REPLICATION GATE
--------------------
The client accepts an unreliable replication message only when BOTH hold
(`FUN_14643e7b0`): its `clientContextInstanceId` matches `port[+0x80]` (a byte,
live value 1), and its counter is strictly greater than `port[+0x78]`
(`m_lastUnreliableReplicationSeq`). That counter is the `SEQ` varint here.
Because it is a varint, advancing it must **re-encode** it: writing a byte
`>= 0x80` turns a one-byte varint into a two-byte one and shifts everything after
it, which is the `Failed to unmarshal … ValidationError` measured in
`research/docs/DECOMP-BACKLOG.md` section 12.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import varint

__all__ = [
    "STATE_BUNDLE_TYPE",
    "TYPE_MARKER",
    "BundleBody",
    "Fragment",
    "FragmentHeader",
    "Record",
    "BundleError",
    "compose_bundle",
    "encode_bundle",
    "encode_type_marker",
    "read_type_marker",
    "decode_bundle",
    "parse_fragment",
    "read_fragment_header",
    "looks_like_state_bundle",
    "split_record_payload",
    "with_replication_seq",
]

STATE_BUNDLE_TYPE = 0x08
# A typed message begins with a two-byte tag then the varint type.
TYPE_MARKER = b"\x00\x01"
# Offsets within a bundle body, from the byte dumps of all 78 captured bundles.
_SEQ_OFFSET = 4  # the replication counter varint
# The prologue is `01 <varint SEQ> <6 invariant bytes>`. The six bytes after the
# seq varint never vary across the capture, which makes them a layout check.
_PROLOGUE_HEAD = b"\x01"
PROLOGUE_TAIL = b"\x01\x01\x01\x01\x00\x00"


class BundleError(ValueError):
    """A state bundle body that does not match the verified layout."""


@dataclass
class FragmentHeader:
    """The two varints that begin every fragment.

    A fragment is `[varint key][varint type_index][payload]` with no length
    field, so this header is all that can be read without knowing the type's
    payload encoding. See the module docstring for the measurement behind it.
    """

    key: int
    type_index: int
    header_size: int


def read_fragment_header(data: bytes, offset: int = 0) -> FragmentHeader:
    """Read a fragment header. Returns the header and its byte size.

    Raises ``BundleError`` if either varint is malformed.
    """
    try:
        key, after_key = varint.decode(data, offset)
        type_index, after_type = varint.decode(data, after_key)
    except varint.VarintError as exc:
        raise BundleError(f"fragment header at {offset}: {exc}") from exc
    return FragmentHeader(
        key=key,
        type_index=type_index,
        header_size=after_type - offset,
    )


@dataclass
class BundleBody:
    """A parsed type-0x08 body.

    `payload` is the length-prefixed blob, which is a sequence of records
    (`[u8 record_id][u8 fragment_count][fragments…]`). The fragment layout inside
    a record is not yet derived, so `payload` is exposed raw rather than walked.
    """

    replication_seq: int
    payload: bytes

    def encode_body(self) -> bytes:
        """Serialize back to the 0x08 body (everything after the type marker)."""
        return (
            _PROLOGUE_HEAD
            + varint.encode(self.replication_seq)
            + PROLOGUE_TAIL
            + varint.encode(len(self.payload))
            + self.payload
        )


def encode_type_marker(type_id: int) -> bytes:
    """`00 01 <varint type>` — the tag every inbound typed message carries."""
    return TYPE_MARKER + varint.encode(type_id)


def read_type_marker(body: bytes) -> tuple[int, int]:
    """Read the typed marker. Returns ``(type_id, offset_after_marker)``."""
    if len(body) < 3 or body[:2] != TYPE_MARKER:
        got = body[:2].hex() if len(body) >= 2 else body.hex()
        raise BundleError(f"missing typed marker (expected 0001, got {got})")
    type_id, offset = varint.decode(body, 2)
    return type_id, offset


def looks_like_state_bundle(body: bytes) -> bool:
    """True when ``body`` starts with a well-formed type-0x08 marker."""
    if len(body) < 3 or body[:2] != TYPE_MARKER:
        return False
    try:
        type_id, _ = varint.decode(body, 2)
    except varint.VarintError:
        return False
    return type_id == STATE_BUNDLE_TYPE


def decode_bundle(body: bytes, *, strict: bool = True) -> BundleBody:
    """Parse a full state bundle body, marker included.

    ``strict`` requires the payload length to reach the end of the body exactly.
    Unlike the previous opaque-payload model, this check is now meaningful: the
    payload is a record sequence with its own internal structure, so a mismatch
    is a real signal rather than a tautology.
    """
    type_id, offset = read_type_marker(body)
    if type_id != STATE_BUNDLE_TYPE:
        raise BundleError(f"not a state bundle: type 0x{type_id:x}")
    if len(body) <= _SEQ_OFFSET:
        raise BundleError("state bundle truncated inside the prologue")
    seq, after_seq = varint.decode(body, _SEQ_OFFSET)
    tail = body[after_seq : after_seq + len(PROLOGUE_TAIL)]
    if tail != PROLOGUE_TAIL:
        # A layout check: if these six bytes move, the build changed and every
        # offset in this module is suspect.
        raise BundleError(
            f"prologue tail mismatch (expected {PROLOGUE_TAIL.hex()}, "
            f"got {tail.hex()})"
        )
    length, after_len = varint.decode(body, after_seq + len(PROLOGUE_TAIL))
    payload = body[after_len:]
    if strict and len(payload) != length:
        raise BundleError(
            f"payload length says {length} but {len(payload)} bytes remain"
        )
    return BundleBody(replication_seq=seq, payload=payload)


def with_replication_seq(body: bytes, seq: int) -> bytes:
    """Return ``body`` with its replication counter set to ``seq``.

    The counter is a varint, so raising it past the client's high-water can widen
    it (53 → 0x80 needs two bytes). This re-encodes rather than overwriting a
    byte, so the prologue and payload stay aligned whatever width the new value
    needs — a raw byte write is what produced the measured `ValidationError`.
    """
    parsed = decode_bundle(body)
    return (
        encode_type_marker(STATE_BUNDLE_TYPE)
        + _PROLOGUE_HEAD
        + varint.encode(seq)
        + PROLOGUE_TAIL
        + varint.encode(len(parsed.payload))
        + parsed.payload
    )


@dataclass(frozen=True)
class Fragment:
    """One `[varint key][varint type_index][payload]` fragment.

    The grammar was DERIVED FROM THE CLIENT, not guessed: a probe hooked the record reader
    (`FUN_146af20d0`), the fragment reader (`FUN_146af2340`) and the shared prefix-varint reader
    (`FUN_14087b5c0`) and logged each fragment's offset from the record start plus the varints read
    inside it. Across the local-player metadata record the reported (key, type) pairs match a
    byte-level parse of the payload exactly, and there is NO length field: the payload length is
    implied by the type. See `research/derived/state-bundle-fragments.json`.
    """

    key: int
    type_index: int
    payload: bytes

    def encode(self) -> bytes:
        return varint.encode(self.key) + varint.encode(self.type_index) + self.payload

    @property
    def header_size(self) -> int:
        return len(varint.encode(self.key)) + len(varint.encode(self.type_index))


@dataclass(frozen=True)
class Record:
    """One `[u8 record_id][u8 fragment_count][fragments…]` record."""

    record_id: int
    fragments: tuple[Fragment, ...]

    def encode(self) -> bytes:
        if not 0 <= self.record_id <= 0xFF:
            raise BundleError(f"record id {self.record_id} outside a byte")
        if not 0 <= len(self.fragments) <= 0xFF:
            raise BundleError(f"{len(self.fragments)} fragments outside a byte")
        return (
            bytes((self.record_id, len(self.fragments)))
            + b"".join(f.encode() for f in self.fragments)
        )


def encode_bundle(replication_seq: int, payload: bytes) -> bytes:
    """Wrap an already-built record payload into a type-0x08 body.

    The inverse of `decode_bundle`, and the right tool when a caller has patched bytes inside a
    payload WITHOUT changing its length: re-encoding through here keeps the prologue and the
    length field aligned whatever width the counter needs, which a raw byte write does not.
    """
    return (
        encode_type_marker(STATE_BUNDLE_TYPE)
        + _PROLOGUE_HEAD
        + varint.encode(replication_seq)
        + PROLOGUE_TAIL
        + varint.encode(len(payload))
        + payload
    )


def compose_bundle(replication_seq: int, records: list[Record]) -> bytes:
    """Build a type-0x08 body from records the SERVER owns.

    This is the difference between forwarding a captured bundle and sending one we composed:
    the caller supplies the replication counter, the record ids, and every fragment's key, type
    and payload. Verified as such — composing the captured local-player record from its fragments
    reproduces the captured body byte for byte.
    """
    return encode_bundle(replication_seq, b"".join(r.encode() for r in records))


def split_record_payload(payload: bytes, boundaries: list[int]) -> list[bytes]:
    """Slice one record's payload into fragments using KNOWN boundaries.

    The boundaries cannot be recomputed from the bytes alone — a fragment carries no length and
    its payload length is implied by its type — so they come from the client
    (`research/derived/state-bundle-fragments.json`) or from a caller that knows the layout.

    ``boundaries`` are offsets into ``payload``, in order, where each fragment STARTS; the last
    fragment runs to the end. They are normally relative to the record, so the first one is the
    record header's size (2: one byte of record id plus one of fragment count) and the bytes
    before it are that header, not a fragment. A first boundary of 0 is also accepted, for a
    caller that passes the fragment region alone.
    """
    if not boundaries:
        raise BundleError("no boundaries given")
    if boundaries[0] < 0 or boundaries != sorted(boundaries) or len(set(boundaries)) != len(boundaries):
        raise BundleError("boundaries must be non-negative and strictly ascending")
    if boundaries[-1] >= len(payload):
        raise BundleError(
            f"last boundary {boundaries[-1]} is past the payload ({len(payload)} bytes)"
        )
    out = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(payload)
        out.append(payload[start:end])
    return out


def parse_fragment(fragment: bytes) -> Fragment:
    """Decode one fragment sliced by a known boundary into (key, type, payload)."""
    try:
        key, after_key = varint.decode(fragment, 0)
        type_index, after_type = varint.decode(fragment, after_key)
    except varint.VarintError as exc:
        raise BundleError(f"fragment header: {exc}") from exc
    return Fragment(key=key, type_index=type_index, payload=fragment[after_type:])
