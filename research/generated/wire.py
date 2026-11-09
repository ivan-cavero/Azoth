# GENERATED FILE -- do not edit by hand.
#
# Produced by `reverse/tools/atlas/ontology-gen.py` (run `python ef.py re
# ontology-gen`) from `research/atlas/ontology/schema.json` and the Atlas concept
# cards. The per-message layouts in MESSAGES are DERIVED from the cards.
#
# Envelope note: every field below is a message BODY field. The record envelope
# (`00 01` + the prefix-varint type) is framing owned by javelin/frame.py and
# javelin/bundle.py and is never a field here.
"""Table-driven encoder/decoder for the closed Atlas codec vocabulary."""

from __future__ import annotations

import re
import struct
import sys as _sys
from pathlib import Path as _Path

_JAVELIN_SRC = _Path(__file__).resolve().parents[2] / "services" / "world" / "src"
if str(_JAVELIN_SRC) not in _sys.path:
    _sys.path.insert(0, str(_JAVELIN_SRC))

# The measured primitive: imported, never duplicated.
from azoth_world.javelin import varint as _prefix_varint  # noqa: E402


class WireCodecError(ValueError):
    """A body that does not match the card-derived layout."""


# The closed vocabulary, from schema.json $defs.codec.
VOCABULARY = (
    'u8',
    'u16be',
    'u16le',
    'u32be',
    'u32le',
    'u64be',
    'u64le',
    'i8',
    'i16be',
    'i32be',
    'i64be',
    'f32be',
    'f32le',
    'f64be',
    'prefix_varint',
    'varint',
    'bool_byte',
    'prefixed_bytes',
    'prefixed_string',
    'guid16',
    'enum8',
    'enum16be',
    'enum32be',
    'bitset8',
    'bitset16',
    'bitset32be',
)
CODEC_PATTERNS = (
    '^bytes\\([1-9][0-9]*\\)$',
    '^fixed_string\\([1-9][0-9]*\\)$',
    '^vec<(u8|u16be|u16le|u32be|u32le|u64be|u64le|i8|i16be|i32be|i64be|f32be|f32le|f64be|enum8|enum16be|enum32be|bool_byte|prefix_varint|varint)>$',
    '^matrix<(u8|u16be|u16le|u32be|u32le|u64be|u64le|i8|i16be|i32be|i64be|f32be|f32le|f64be|enum8|enum16be|enum32be|bool_byte|prefix_varint|varint)>$',
    '^nested\\([a-z][a-z0-9.-]*\\.[a-z0-9][a-z0-9.-]*\\)$',
    '^counted\\((?:u8|u16be|u16le|u32be|u32le|u64be|u64le|i8|i16be|i32be|i64be|f32be|f32le|f64be|enum8|enum16be|enum32be|bool_byte|prefix_varint|varint|guid16|nested\\([a-z][a-z0-9.-]*\\.[a-z0-9][a-z0-9.-]*\\))\\)$',
    '^optional\\((?:u8|u16be|u16le|u32be|u32le|u64be|u64le|i8|i16be|i32be|i64be|f32be|f32le|f64be|enum8|enum16be|enum32be|bool_byte|prefix_varint|varint|guid16|nested\\([a-z][a-z0-9.-]*\\.[a-z0-9][a-z0-9.-]*\\))\\)$',
    '^masked_counted\\((?:u8|u16be|u16le|u32be|u32le|u64be|u64le|i8|i16be|i32be|i64be|f32be|f32le|f64be|enum8|enum16be|enum32be|bool_byte|prefix_varint|varint|guid16|nested\\([a-z][a-z0-9.-]*\\.[a-z0-9][a-z0-9.-]*\\))\\)$',
    '^opaque\\([a-z][a-z0-9_.-]*\\)$',
)


_STRUCT = {
    "u8": "B",
    "i8": "b",
    "u16be": ">H",
    "u16le": "<H",
    "i16be": ">h",
    "u32be": ">I",
    "u32le": "<I",
    "i32be": ">i",
    "u64be": ">Q",
    "u64le": "<Q",
    "i64be": ">q",
    "f32be": ">f",
    "f32le": "<f",
    "f64be": ">d",
    "enum8": "B",
    "enum16be": ">H",
    "enum32be": ">I",
    "bitset8": "B",
    "bitset16": ">H",
    "bitset32be": ">I",
}
_FIXED = re.compile(r"^(?:bytes|fixed_string)\(([1-9][0-9]*)\)$")
_VEC = re.compile(r"^vec<(.+)>$")
_VEC_LITERAL = re.compile(r"^vec<(.+)>\[([0-9]+)\]$")
_MATRIX = re.compile(r"^matrix<(.+)>$")
_NESTED = re.compile(r"^nested\((.+)\)$")
_COUNTED = re.compile(r"^counted\((.+)\)$")
_OPTIONAL = re.compile(r"^optional\((.+)\)$")
_MASKED_COUNTED = re.compile(r"^masked_counted\((.+)\)$")


def _read_exact(data, offset, count):
    end = offset + count
    if end > len(data):
        raise WireCodecError(
            f"truncated: need {count} byte(s) at {offset}, have {len(data) - offset}"
        )
    return data[offset:end], end


def _decode_leb128(data, offset):
    # `varint` (plain LEB128) is the vocabulary's other varint; `prefix_varint`
    # is the measured Javelin one and comes from javelin/varint.py above.
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise WireCodecError("truncated LEB128 varint")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
        if shift > 63:
            raise WireCodecError("LEB128 varint is longer than 10 bytes")


def _encode_leb128(value):
    if value < 0:
        raise WireCodecError(f"LEB128 cannot encode negative value {value}")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _decode_sequence(element, data, offset):
    count, offset = _prefix_varint.decode(data, offset)
    items = []
    for _ in range(count):
        item, offset = decode_field(element, data, offset)
        items.append(item)
    return items, offset


def _lowest_bit(value):
    return (value & -value).bit_length() - 1


def _decode_wide_varint(data, offset):
    """The client's wide prefix varint (FUN_14087b910): up to eight bytes.

    The number of leading 1-bits in the first byte gives the continuation count;
    the first byte's low bits are the value's lowest bits and the continuation
    bytes are little-endian above them. A mask can therefore be 56 bits wide.
    """
    if offset >= len(data):
        raise WireCodecError("truncated wide prefix varint")
    first = data[offset]
    n = 0
    bit = 0x80
    while first & bit:
        n += 1
        bit >>= 1
    if n > 7:
        raise WireCodecError("wide prefix varint longer than eight bytes")
    end = offset + 1 + n
    if end > len(data):
        raise WireCodecError("truncated wide prefix varint")
    if n == 0:
        return first, end
    shift = 7 - n
    cont = int.from_bytes(data[offset + 1:end], "little")
    return (cont << shift) | (first & ((1 << shift) - 1)), end


def _encode_wide_varint(value):
    """The canonical bytes of the client's wide prefix varint."""
    if value < 0 or value >= (1 << 56):
        raise WireCodecError(f"wide prefix varint {value:#x} out of range")
    if value < 0x80:
        return bytes([value])
    n = 1
    while n < 7 and value >= (1 << (7 + 7 * n)):
        n += 1
    shift = 7 - n
    leading = ((0xFF << (8 - n)) & 0xFF) | (value & ((1 << shift) - 1))
    return bytes([leading]) + (value >> shift).to_bytes(n, "little")


def _decode_mask(bits, continuation, varint, data, offset):
    """One presence-mask value: the bitmask over the items it selects.

    A level WITH a continuation is a sequence: it reads mask bytes while the
    continuation bit is set, and each byte contributes `bits` low-first item
    bits. A level WITH `varint` is one wide prefix varint whose value is the
    bitmask. A level WITHOUT either is exactly one byte.
    """
    if varint:
        return _decode_wide_varint(data, offset)
    mask = 0
    shift = 0
    while True:
        raw, offset = _read_exact(data, offset, 1)
        byte = raw[0]
        mask |= (byte & ((1 << bits) - 1)) << shift
        if continuation is None or not byte & continuation:
            return mask, offset
        shift += bits


def _encode_mask(bits, continuation, varint, mask):
    """The canonical bytes of one presence-mask value (the fewest bytes)."""
    if varint:
        return _encode_wide_varint(mask)
    out = bytearray()
    rest = mask
    while True:
        byte = rest & ((1 << bits) - 1)
        rest >>= bits
        if rest and continuation is None:
            raise WireCodecError(
                f"presence mask {mask:#x} does not fit one {bits}-bit byte"
            )
        if rest:
            byte |= continuation
        out.append(byte)
        if not rest:
            return bytes(out)


def _decode_members(spec, data, offset):
    """Decode one record: a flat field list, or a two-level presence mask."""
    presence = spec.get("presence")
    if presence is None:
        values = {}
        for name, type_name in spec["fields"]:
            values[name], offset = decode_field(type_name, data, offset)
        return values, offset

    group_name, group_bits, group_continuation, group_varint = presence["group"]
    member_name, member_bits, continuation, member_varint = presence["member"]
    values = {}
    group_mask, offset = _decode_mask(
        group_bits, group_continuation, group_varint, data, offset
    )
    declared = 0
    for _index, bits, _members in presence["groups"]:
        declared |= bits
    unknown = group_mask & ~declared
    if unknown:
        raise WireCodecError(
            f"{group_name} bit {_lowest_bit(unknown)} names no declared group"
        )
    values[group_name] = group_mask
    groups = []
    for _index, bits, members in presence["groups"]:
        if not group_mask & bits:
            continue
        entry_mask, offset = _decode_mask(
            member_bits, continuation, member_varint, data, offset
        )
        declared_members = 0
        for _member, member_bit, _name, _codec in members:
            declared_members |= member_bit
        unknown = entry_mask & ~declared_members
        if unknown:
            raise WireCodecError(
                f"{member_name} bit {_lowest_bit(unknown)} names no declared member"
            )
        entries = {}
        for member, bit, name, type_name in members:
            if entry_mask & bit:
                entries[name], offset = decode_field(type_name, data, offset)
        groups.append({member_name: entry_mask, "entries": entries})
    values["groups"] = groups
    return values, offset


def _encode_members(spec, values):
    """Encode one record: a flat field list, or a two-level presence mask."""
    presence = spec.get("presence")
    if presence is None:
        out = bytearray()
        for name, type_name in spec["fields"]:
            if name not in values:
                raise WireCodecError(f"{spec.get('uid')}: missing field {name!r}")
            out += encode_field(type_name, values[name])
        return bytes(out)

    group_name, group_bits, group_continuation, group_varint = presence["group"]
    member_name, member_bits, continuation, member_varint = presence["member"]
    group_mask = values[group_name]
    out = bytearray(
        _encode_mask(group_bits, group_continuation, group_varint, group_mask)
    )
    written = values.get("groups") or []
    cursor = 0
    for _index, bits, members in presence["groups"]:
        if not group_mask & bits:
            continue
        if cursor >= len(written):
            raise WireCodecError(f"{spec.get('uid')}: {group_name} selects a group the value omits")
        group = written[cursor]
        cursor += 1
        entry_mask = group[member_name]
        out += _encode_mask(member_bits, continuation, member_varint, entry_mask)
        for member, bit, name, type_name in members:
            if entry_mask & bit:
                if name not in group["entries"]:
                    raise WireCodecError(
                        f"{spec.get('uid')}: {member_name} selects member {name!r} "
                        f"the value omits"
                    )
                out += encode_field(type_name, group["entries"][name])
    if cursor != len(written):
        raise WireCodecError(
            f"{spec.get('uid')}: {len(written) - cursor} group(s) the mask does not select"
        )
    return bytes(out)


def _decode_matrix(element, data, offset):
    rows, offset = _prefix_varint.decode(data, offset)
    cols, offset = _prefix_varint.decode(data, offset)
    out = []
    for _ in range(rows):
        row = []
        for _ in range(cols):
            item, offset = decode_field(element, data, offset)
            row.append(item)
        out.append(row)
    return out, offset


def decode_field(type_name, data, offset=0):
    """Decode one closed-vocabulary value. Returns (value, next_offset)."""
    if type_name in _STRUCT:
        size = struct.calcsize(_STRUCT[type_name])
        raw, offset = _read_exact(data, offset, size)
        return struct.unpack(_STRUCT[type_name], raw)[0], offset
    if type_name == "bool_byte":
        raw, offset = _read_exact(data, offset, 1)
        return raw[0] != 0, offset
    if type_name == "prefix_varint":
        return _prefix_varint.decode(data, offset)
    if type_name == "varint":
        return _decode_leb128(data, offset)
    if type_name == "guid16":
        return _read_exact(data, offset, 16)
    match = _FIXED.match(type_name)
    if match:
        return _read_exact(data, offset, int(match.group(1)))
    if type_name == "prefixed_bytes":
        length, offset = _prefix_varint.decode(data, offset)
        return _read_exact(data, offset, length)
    if type_name == "prefixed_string":
        length, offset = _prefix_varint.decode(data, offset)
        raw, offset = _read_exact(data, offset, length)
        return raw.decode("utf-8"), offset
    match = _VEC_LITERAL.match(type_name)
    if match:
        # A literal count is part of the layout: no length prefix on the wire.
        element, count = match.group(1), int(match.group(2))
        items = []
        for _ in range(count):
            item, offset = decode_field(element, data, offset)
            items.append(item)
        return items, offset
    match = _VEC.match(type_name)
    if match:
        return _decode_sequence(match.group(1), data, offset)
    match = _MATRIX.match(type_name)
    if match:
        return _decode_matrix(match.group(1), data, offset)
    match = _COUNTED.match(type_name)
    if match:
        return _decode_sequence(match.group(1), data, offset)
    match = _MASKED_COUNTED.match(type_name)
    if match:
        element = match.group(1)
        count, offset = _prefix_varint.decode(data, offset)
        items = []
        remaining = count
        while remaining:
            chunk = min(remaining, 8)
            raw, offset = _read_exact(data, offset, 1)
            wanted = (1 << chunk) - 1
            if raw[0] != wanted:
                raise WireCodecError(
                    f"masked_counted {type_name!r} mask byte {raw[0]:#04x} at "
                    f"{offset - 1} does not declare every element of its chunk "
                    f"({wanted:#04x})"
                )
            for _ in range(chunk):
                item, offset = decode_field(element, data, offset)
                items.append(item)
            remaining -= chunk
        return items, offset
    match = _OPTIONAL.match(type_name)
    if match:
        flag, offset = _read_exact(data, offset, 1)
        if flag[0] > 1:
            raise WireCodecError(
                f"optional {type_name!r} flag is {flag[0]}, not zero or one"
            )
        if flag[0] == 0:
            return None, offset
        return decode_field(match.group(1), data, offset)
    match = _NESTED.match(type_name)
    if match:
        spec = CODECS.get(match.group(1))
        if spec is None:
            raise WireCodecError(f"no card-derived codec for {match.group(1)}")
        return _decode_members(spec, data, offset)
    if type_name.startswith("opaque("):
        raise WireCodecError(f"opaque codec {type_name!r} is not codegen-ready")
    raise WireCodecError(f"{type_name!r} is not a closed-vocabulary codec")


def encode_field(type_name, value):
    """Encode one closed-vocabulary value to bytes."""
    if type_name in _STRUCT:
        return struct.pack(_STRUCT[type_name], value)
    if type_name == "bool_byte":
        return bytes([1 if value else 0])
    if type_name == "prefix_varint":
        return _prefix_varint.encode(int(value))
    if type_name == "varint":
        return _encode_leb128(int(value))
    if type_name == "guid16":
        raw = bytes(value)
        if len(raw) != 16:
            raise WireCodecError(f"guid16 needs 16 bytes, got {len(raw)}")
        return raw
    match = _FIXED.match(type_name)
    if match:
        size = int(match.group(1))
        raw = value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
        if len(raw) > size:
            raise WireCodecError(f"{type_name} holds {size} bytes, got {len(raw)}")
        return bytes(raw) + b"\x00" * (size - len(raw))
    if type_name == "prefixed_bytes":
        raw = bytes(value)
        return _prefix_varint.encode(len(raw)) + raw
    if type_name == "prefixed_string":
        raw = str(value).encode("utf-8")
        return _prefix_varint.encode(len(raw)) + raw
    match = _VEC_LITERAL.match(type_name)
    if match:
        # A literal count is part of the layout: no length prefix on the wire.
        element, count = match.group(1), int(match.group(2))
        items = list(value)
        if len(items) != count:
            raise WireCodecError(
                f"{type_name} holds exactly {count} item(s), got {len(items)}"
            )
        out = bytearray()
        for item in items:
            out += encode_field(element, item)
        return bytes(out)
    match = _VEC.match(type_name)
    if match:
        items = list(value)
        out = bytearray(_prefix_varint.encode(len(items)))
        for item in items:
            out += encode_field(match.group(1), item)
        return bytes(out)
    match = _MATRIX.match(type_name)
    if match:
        rows = [list(row) for row in value]
        cols = len(rows[0]) if rows else 0
        out = bytearray(_prefix_varint.encode(len(rows)))
        out += _prefix_varint.encode(cols)
        for row in rows:
            if len(row) != cols:
                raise WireCodecError("matrix rows must all share one column count")
            for item in row:
                out += encode_field(match.group(1), item)
        return bytes(out)
    match = _COUNTED.match(type_name)
    if match:
        items = list(value)
        out = bytearray(_prefix_varint.encode(len(items)))
        for item in items:
            out += encode_field(match.group(1), item)
        return bytes(out)
    match = _MASKED_COUNTED.match(type_name)
    if match:
        element = match.group(1)
        items = list(value)
        out = bytearray(_prefix_varint.encode(len(items)))
        cursor = 0
        while cursor < len(items):
            chunk = min(len(items) - cursor, 8)
            out.append((1 << chunk) - 1)
            for item in items[cursor : cursor + chunk]:
                out += encode_field(element, item)
            cursor += chunk
        return bytes(out)
    match = _OPTIONAL.match(type_name)
    if match:
        if value is None:
            return b"\x00"
        return b"\x01" + encode_field(match.group(1), value)
    match = _NESTED.match(type_name)
    if match:
        spec = CODECS.get(match.group(1))
        if spec is None:
            raise WireCodecError(f"no card-derived codec for {match.group(1)}")
        return _encode_members(spec, value)
    raise WireCodecError(f"{type_name!r} is not a closed-vocabulary codec")


def wire_id(uid):
    """The wire id for a card uid, from the card-derived table."""
    for wire, spec in MESSAGES.items():
        if spec["uid"] == uid:
            return wire
    raise WireCodecError(f"no message card {uid!r}")


def decode(wire, body, *, offset=0, require_full=True):
    """Decode a message BODY into {field_name: value}."""
    spec = MESSAGES.get(wire)
    if spec is None:
        raise WireCodecError(f"no card-derived layout for wire {wire}")
    values, cursor = _decode_members(spec, body, offset)
    if require_full and cursor != len(body):
        raise WireCodecError(
            f"wire {wire}: {len(body) - cursor} trailing byte(s) after the last field"
        )
    return values


def encode(wire, message):
    """Encode {field_name: value} into a message BODY."""
    spec = MESSAGES.get(wire)
    if spec is None:
        raise WireCodecError(f"no card-derived layout for wire {wire}")
    return _encode_members(spec, message)


def decode_codec(uid, body, *, require_full=True):
    """Decode a named nested sub-codec (not a message) into {field_name: value}."""
    spec = CODECS.get(uid)
    if spec is None:
        raise WireCodecError(f"no card-derived codec for {uid}")
    values, cursor = _decode_members(spec, body, 0)
    if require_full and cursor != len(body):
        raise WireCodecError(
            f"codec {uid}: {len(body) - cursor} trailing byte(s) after the last field"
        )
    return values


def encode_codec(uid, message):
    """Encode {field_name: value} for a named nested sub-codec."""
    spec = CODECS.get(uid)
    if spec is None:
        raise WireCodecError(f"no card-derived codec for {uid}")
    return _encode_members(spec, message)


# --- card-derived message layouts (BODY fields only) ---
MESSAGES = {
    3: {
        'uid': 'flow.world-entry.rung.registration',
        'name': 'Ladder: Registration response',
        'direction': 'S2C',
        'fields': (
            ('unresolved_u32', 'u32be'),
            ('unresolved_u64', 'u64be'),
            ('unresolved_block', 'prefixed_bytes'),
            ('server_version', 'prefixed_string'),
            ('trailing_bool_0', 'bool_byte'),
            ('trailing_bool_1', 'bool_byte'),
            ('trailing_bool_2', 'bool_byte'),
            ('trailing_bool_3', 'bool_byte'),
        ),
    },
    106: {
        'uid': 'msg.update',
        'name': 'UpdateMsg',
        'direction': 'S2C',
        'fields': (
            ('blob', 'prefixed_bytes'),
        ),
    },
    164: {
        'uid': 'msg.client-add-entry',
        'name': 'ClientAddEntryMsg',
        'direction': 'S2C',
        'fields': (
            ('actor_id', 'guid16'),
        ),
    },
    335: {
        'uid': 'msg.time-synch-0x14f',
        'name': 'TimeSynchMsg',
        'direction': 'S2C',
        'fields': (
            ('unresolved_prefix', 'bytes(2)'),
            ('time_high', 'u16be'),
            ('time_low', 'u32be'),
        ),
    },
    349: {
        'uid': 'flow.world-entry.rung.ping',
        'name': 'Ladder: Ping heartbeat',
        'direction': 'S2C',
        'fields': (
            ('unresolved_prefix', 'bytes(2)'),
            ('tick_high', 'u16be'),
            ('tick_low', 'u32be'),
        ),
    },
    387: {
        'uid': 'msg.set-replicate-storage',
        'name': 'GlobalStorageComponentServerFacet_SetReplicateStorage',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('field_c', 'bytes(16)'),
        ),
    },
    446: {
        'uid': 'flow.world-entry.rung.coatlicue-timing',
        'name': 'Ladder: CoatlicueTimingConfigurationConnected',
        'direction': 'S2C',
        'fields': (
            ('vtable_tag', 'u32be'),
            ('unresolved_block', 'bytes(32)'),
            ('shared_block', 'bytes(36)'),
        ),
    },
    1034: {
        'uid': 'flow.world-entry.rung.calendar-connected',
        'name': 'Ladder: CalendarConnected',
        'direction': 'S2C',
        'fields': (
            ('vtable_tag', 'u32be'),
            ('unresolved_block', 'bytes(32)'),
            ('shared_block', 'bytes(36)'),
        ),
    },
    1458: {
        'uid': 'msg.objectives-update-tracked-objectives',
        'name': 'ObjectivesComponentServerFacet_UpdateTrackedObjectives',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('tracked_objective_ids', 'vec<u64be>'),
        ),
    },
    1502: {
        'uid': 'msg.request-spend-attribute-points',
        'name': 'AttributeComponentServerFacet_RequestSpendAttributePoints',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('attribute_indices', 'vec<u32be>'),
            ('points', 'vec<u32be>'),
        ),
    },
    1628: {
        'uid': 'flow.world-entry.rung.self-identification',
        'name': 'Ladder: SelfIdentification',
        'direction': 'S2C',
        'fields': (
            ('prefix_lead', 'u8'),
            ('identity_guid_prefix', 'guid16'),
            ('vtable_tag', 'u32be'),
            ('prefix_data', 'bytes(107)'),
            ('grid_side', 'u8'),
            ('grid_header', 'bytes(2)'),
            ('grid_cells', 'bytes(12544)'),
            ('tail_zeros', 'bytes(10)'),
            ('tail_lead', 'u8'),
            ('identity_guid_tail', 'guid16'),
        ),
    },
    1635: {
        'uid': 'flow.world-entry.rung.level-info',
        'name': 'Ladder: LevelInfoChanged',
        'direction': 'S2C',
        'fields': (
            ('level_name', 'prefixed_string'),
            ('level_path', 'prefixed_string'),
            ('level_bounds', 'vec<f32be>[4]'),
            ('unresolved_u64', 'u64be'),
            ('unresolved_u32', 'u32be'),
            ('session_nonce', 'u64be'),
            ('unresolved_group', 'bytes(10)'),
            ('level_context_key', 'u64be'),
        ),
    },
    2278: {
        'uid': 'msg.contracts-on-lookup-contracts-by-participant',
        'name': 'ContractsComponentClientFacet_OnLookupContractsByParticipant',
        'direction': 'S2C',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('lookup_id', 'bytes(16)'),
            ('trailing_block', 'bytes(6)'),
        ),
    },
    2297: {
        'uid': 'msg.territory-detector-attempt-territory-unlock',
        'name': 'TerritoryDetectorComponentServerFacet_AttemptTerritoryUnlock',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('unlock_token', 'guid16'),
            ('field_c', 'u64be'),
            ('field_d', 'u64be'),
            ('field_e', 'u16be'),
            ('field_f', 'u32be'),
        ),
    },
    2515: {
        'uid': 'msg.receive-settings-from-client',
        'name': 'PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('field_c', 'u32be'),
        ),
    },
    2556: {
        'uid': 'msg.contracts-lookup-contracts-by-participant',
        'name': 'ContractsComponentServerFacet_LookupContractsByParticipant',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('participant_id', 'bytes(16)'),
            ('u32_be_1', 'u32be'),
            ('u32_be_2', 'u32be'),
            ('u32_be_3', 'u32be'),
            ('blob_64', 'prefixed_bytes'),
            ('blob_256', 'prefixed_bytes'),
            ('count_u32', 'u32be'),
            ('index_ids', 'vec<u32be>'),
            ('type_ids', 'vec<u16be>'),
            ('trailing_id', 'bytes(16)'),
        ),
    },
    2617: {
        'uid': 'msg.objectives-notify-open-ui-screen',
        'name': 'ObjectivesComponentServerFacet_NotifyOpenUiScreen',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('screen_id', 'u32be'),
        ),
    },
    2709: {
        'uid': 'msg.objectives-set-objective-auto-pinning',
        'name': 'ObjectivesComponentServerFacet_SetObjectiveAutoPinning',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('auto_pinning_flags', 'vec<bool_byte>'),
        ),
    },
    3895: {
        'uid': 'msg.server-equip-item',
        'name': 'PaperdollComponentServerFacet_ServerEquipItem',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('field_c', 'u32be'),
            ('field_d', 'u32be'),
            ('field_e', 'u32be'),
            ('item_id', 'guid16'),
            ('field_g', 'bool_byte'),
        ),
    },
    4147: {
        'uid': 'msg.social-receive-available-titles',
        'name': 'SocialComponentClientFacet_ReceiveAvailableTitles',
        'direction': 'S2C',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('title_ids', 'vec<u32be>'),
            ('title_selection_ids', 'vec<u32be>'),
        ),
    },
    4199: {
        'uid': 'msg.voice-chat-service-registered',
        'name': 'VoiceChatComponentClientFacet_OnVoiceChatServiceRegistered',
        'direction': 'S2C',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('api_server_uri', 'prefixed_string'),
            ('login_token', 'prefixed_string'),
            ('realm', 'prefixed_string'),
            ('service_flag', 'bool_byte'),
        ),
    },
    4246: {
        'uid': 'msg.time-sync-time-change',
        'name': 'TimeComponentClientFacet_SyncTimeChange',
        'direction': 'S2C',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('horizon_angle', 'f32be'),
            ('scale_a', 'f32be'),
            ('scale_b', 'f32be'),
            ('day_length_seconds', 'u32be'),
            ('day_phase_index', 'u32be'),
            ('day_switch_seconds', 'u32be'),
            ('hour_seconds', 'u32be'),
            ('seconds_per_hour', 'u32be'),
            ('half_hour_seconds', 'u32be'),
            ('time_of_day', 'u64be'),
            ('phase_rise_start', 'f32be'),
            ('phase_rise_end', 'f32be'),
            ('phase_set_pos', 'f32be'),
            ('phase_set_end', 'f32be'),
        ),
    },
    4247: {
        'uid': 'msg.time-sync-day-phase',
        'name': 'TimeComponentClientFacet_SyncDayPhase',
        'direction': 'S2C',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('day_phase', 'u32be'),
        ),
    },
    4248: {
        'uid': 'msg.time-sync-to-client',
        'name': 'TimeComponentServerFacet_SyncToClient',
        'direction': 'C2S',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
        ),
    },
    6310: {
        'uid': 'msg.grid-tracking-update-phasing',
        'name': 'GridTrackingComponentClientFacet_UpdatePhasing',
        'direction': 'S2C',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('tail_flags', 'u32be'),
            ('session_nonce', 'u64be'),
            ('tail_tag', 'bytes(6)'),
            ('tail_discriminator', 'u8'),
            ('sequence_counter', 'u8'),
        ),
    },
    7048: {
        'uid': 'msg.global-storage-receive-storage-search-items',
        'name': 'GlobalStorageComponentClientFacet_ReceiveStorageSearchItems',
        'direction': 'S2C',
        'fields': (
            ('local_facet_id', 'u64be'),
            ('local_actor_id_word0', 'u64be'),
            ('search_id', 'bytes(16)'),
            ('empty_search_tail', 'bytes(6)'),
        ),
    },
}

# --- card-derived nested sub-codecs (not messages) ---
CODECS = {
    'codec.alc-replicated-state': {
        'name': 'ALCReplicatedState',
        'fields': (
            ('idRel', 'u8'),
            ('timeOffsetRel', 'u8'),
            ('slayerSeqTimeRel0', 'u8'),
            ('slayerSeqTimeAbs0', 'u16be'),
            ('slayerSeqTimeRel1', 'u8'),
            ('slayerSeqTimeAbs1', 'u16be'),
            ('slayerSeqTimeRel2', 'u8'),
            ('slayerSeqTimeAbs2', 'u16be'),
            ('slayerSeqTimeRel3', 'u8'),
            ('slayerSeqTimeAbs3', 'u16be'),
            ('worldPosRel', 'bytes(3)'),
            ('lookDir', 'bytes(2)'),
            ('slayerStateId0', 'prefix_varint'),
            ('slayerStateIdStarted0', 'u16be'),
            ('slayerSequenceId0', 'prefix_varint'),
            ('slayerStateId1', 'prefix_varint'),
            ('slayerStateIdStarted1', 'u16be'),
            ('slayerSequenceId1', 'prefix_varint'),
            ('slayerStateId2', 'prefix_varint'),
            ('slayerStateIdStarted2', 'u16be'),
            ('slayerSequenceId2', 'prefix_varint'),
            ('slayerStateId3', 'prefix_varint'),
            ('slayerStateIdStarted3', 'u16be'),
            ('slayerSequenceId3', 'prefix_varint'),
            ('timeOffsetAbs', 'u8'),
            ('wpnaccrystance', 'u16be'),
            ('slayerScriptLayers', 'u8'),
            ('slayerScriptFlags', 'prefix_varint'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 8, None, True),
            'groups': (
                (0, 1, (
                    (0, 1, 'idRel', 'u8'),
                    (1, 2, 'timeOffsetRel', 'u8'),
                    (2, 4, 'slayerSeqTimeRel0', 'u8'),
                    (3, 8, 'slayerSeqTimeAbs0', 'u16be'),
                    (4, 16, 'slayerSeqTimeRel1', 'u8'),
                    (5, 32, 'slayerSeqTimeAbs1', 'u16be'),
                    (6, 64, 'slayerSeqTimeRel2', 'u8'),
                    (7, 128, 'slayerSeqTimeAbs2', 'u16be'),
                    (8, 256, 'slayerSeqTimeRel3', 'u8'),
                    (9, 512, 'slayerSeqTimeAbs3', 'u16be'),
                    (10, 1024, 'worldPosRel', 'bytes(3)'),
                    (12, 4096, 'lookDir', 'bytes(2)'),
                    (13, 8192, 'slayerStateId0', 'prefix_varint'),
                    (14, 16384, 'slayerStateIdStarted0', 'u16be'),
                    (15, 32768, 'slayerSequenceId0', 'prefix_varint'),
                    (16, 65536, 'slayerStateId1', 'prefix_varint'),
                    (17, 131072, 'slayerStateIdStarted1', 'u16be'),
                    (18, 262144, 'slayerSequenceId1', 'prefix_varint'),
                    (19, 524288, 'slayerStateId2', 'prefix_varint'),
                    (20, 1048576, 'slayerStateIdStarted2', 'u16be'),
                    (21, 2097152, 'slayerSequenceId2', 'prefix_varint'),
                    (22, 4194304, 'slayerStateId3', 'prefix_varint'),
                    (23, 8388608, 'slayerStateIdStarted3', 'u16be'),
                    (24, 16777216, 'slayerSequenceId3', 'prefix_varint'),
                    (26, 67108864, 'timeOffsetAbs', 'u8'),
                    (36, 68719476736, 'wpnaccrystance', 'u16be'),
                    (47, 140737488355328, 'slayerScriptLayers', 'u8'),
                    (48, 281474976710656, 'slayerScriptFlags', 'prefix_varint'),
                )),
            ),
        },
    },
    'codec.contracts.blob-256': {
        'name': 'Contracts nested sub-codec B',
        'fields': (
            ('payload', 'prefixed_bytes'),
        ),
    },
    'codec.contracts.blob-64': {
        'name': 'Contracts nested sub-codec A',
        'fields': (
            ('payload', 'prefixed_bytes'),
        ),
    },
    'codec.contracts.u32-vector-5': {
        'name': 'Contracts nested sub-codec C',
        'fields': (
            ('values', 'vec<u32be>'),
        ),
    },
    'codec.entitlement-balance': {
        'name': 'EntitlementBalance',
        'fields': (
            ('left', 'u32be'),
            ('right', 'u32be'),
        ),
    },
    'codec.entitlement-balances': {
        'name': 'EntitlementBalances',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(nested(codec.entitlement-balance))'),
        ),
    },
    'codec.entitlement-entitlements': {
        'name': 'EntitlementEntitlements',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(nested(codec.entitlement-entry))'),
        ),
    },
    'codec.entitlement-entry': {
        'name': 'EntitlementEntry',
        'fields': (
            ('entitlement', 'u8'),
        ),
    },
    'codec.entitlement-received': {
        'name': 'EntitlementReceived',
        'fields': (
            ('received', 'bool_byte'),
        ),
    },
    'codec.entitlement-replicated-state': {
        'name': 'EntitlementComponentReplicatedState',
        'fields': (
            ('entitlements', 'nested(codec.entitlement-entitlements)'),
            ('balances', 'nested(codec.entitlement-balances)'),
            ('entitlementsReceived', 'nested(codec.entitlement-received)'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (0, 1, (
                    (0, 1, 'entitlements', 'nested(codec.entitlement-entitlements)'),
                    (1, 2, 'balances', 'nested(codec.entitlement-balances)'),
                    (2, 4, 'entitlementsReceived', 'nested(codec.entitlement-received)'),
                )),
            ),
        },
    },
    'codec.objectives-active-objective': {
        'name': 'ObjectivesActiveObjective',
        'fields': (
            ('u32_a08', 'u32be'),
            ('u64_a10', 'u64be'),
            ('u32_a18', 'u32be'),
            ('guid_a1c', 'bytes(16)'),
            ('u64_a38', 'u64be'),
            ('u16_a40', 'u16be'),
            ('u8_a42', 'u8'),
            ('u8_a43', 'u8'),
            ('u8_a44', 'u8'),
            ('u8_a45', 'u8'),
            ('u64_a50', 'u64be'),
            ('u8_a58', 'u8'),
            ('index_list', 'vec<u32be>'),
        ),
    },
    'codec.objectives-active-objectives': {
        'name': 'ObjectivesActiveObjectives',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(nested(codec.objectives-active-objective))'),
        ),
    },
    'codec.objectives-completed-objectives': {
        'name': 'ObjectivesCompletedObjectives',
        'fields': (
            ('elements', 'masked_counted(nested(codec.objectives-tracked-objective))'),
        ),
    },
    'codec.objectives-replicated-state': {
        'name': 'ObjectivesComponentReplicatedState',
        'fields': (
            ('trackedObjectives', 'nested(codec.objectives-tracked-objectives)'),
            ('completedObjectives', 'nested(codec.objectives-completed-objectives)'),
            ('activeObjectives', 'nested(codec.objectives-active-objectives)'),
            ('taskStates', 'nested(codec.objectives-task-states)'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (1, 2, (
                    (1, 2, 'trackedObjectives', 'nested(codec.objectives-tracked-objectives)'),
                    (2, 4, 'completedObjectives', 'nested(codec.objectives-completed-objectives)'),
                    (3, 8, 'activeObjectives', 'nested(codec.objectives-active-objectives)'),
                    (4, 16, 'taskStates', 'nested(codec.objectives-task-states)'),
                )),
            ),
        },
    },
    'codec.objectives-task-state': {
        'name': 'ObjectivesTaskState',
        'fields': (
            ('u64_a10', 'u64be'),
            ('u8_a18', 'u8'),
            ('u32_a1c', 'u32be'),
            ('u32_a20', 'u32be'),
            ('u8_a24', 'u8'),
        ),
    },
    'codec.objectives-task-states': {
        'name': 'ObjectivesTaskStates',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(nested(codec.objectives-task-state))'),
        ),
    },
    'codec.objectives-tracked-objective': {
        'name': 'ObjectivesTrackedObjective',
        'fields': (
            ('id', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('value', 'u64be'),
        ),
    },
    'codec.objectives-tracked-objectives': {
        'name': 'ObjectivesTrackedObjectives',
        'fields': (
            ('elements', 'masked_counted(nested(codec.objectives-tracked-objective))'),
        ),
    },
    'codec.player-component-replicated-state': {
        'name': 'PlayerComponentReplicatedState',
        'fields': (
            ('lookingThroughLoadout', 'nested(codec.player-looking-through-loadout)'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (1, 2, (
                    (3, 8, 'lookingThroughLoadout', 'nested(codec.player-looking-through-loadout)'),
                )),
            ),
        },
    },
    'codec.player-looking-through-loadout': {
        'name': 'PlayerLookingThroughLoadout',
        'fields': (
            ('value', 'bool_byte'),
        ),
    },
    'codec.seasons-rewards-replicated-state': {
        'name': 'SeasonsRewardsReplicatedState',
        'fields': (
            ('cardTemplate', 'nested(codec.seasons-rewards-u8-list)'),
            ('stampedSquares', 'nested(codec.seasons-rewards-u8-list)'),
            ('wildStampedSquares', 'u8'),
            ('rewardClaimed', 'bool_byte'),
            ('rerollCount', 'u8'),
            ('activitiesTasks', 'nested(codec.seasons-rewards-u64-list)'),
            ('wildStampCount', 'u32be'),
            ('wildStampAwardBound', 'u32be'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (0, 1, (
                    (0, 1, 'cardTemplate', 'nested(codec.seasons-rewards-u8-list)'),
                    (2, 4, 'stampedSquares', 'nested(codec.seasons-rewards-u8-list)'),
                    (3, 8, 'wildStampedSquares', 'u8'),
                    (4, 16, 'rewardClaimed', 'bool_byte'),
                    (5, 32, 'rerollCount', 'u8'),
                    (6, 64, 'activitiesTasks', 'nested(codec.seasons-rewards-u64-list)'),
                    (8, 256, 'wildStampCount', 'u32be'),
                    (9, 512, 'wildStampAwardBound', 'u32be'),
                )),
            ),
        },
    },
    'codec.seasons-rewards-tracked-stat-replicated-state': {
        'name': 'SeasonsRewardsTrackedStatReplicatedState',
        'fields': (
            ('initialized', 'bool_byte'),
            ('groupList', 'nested(codec.seasons-rewards-u32-list)'),
            ('groupCountList', 'nested(codec.seasons-rewards-u16-list)'),
            ('groupStatIndex', 'nested(codec.seasons-rewards-u16-list)'),
            ('groupStatValue', 'nested(codec.seasons-rewards-u32-list)'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (0, 1, (
                    (0, 1, 'initialized', 'bool_byte'),
                    (1, 2, 'groupList', 'nested(codec.seasons-rewards-u32-list)'),
                    (2, 4, 'groupCountList', 'nested(codec.seasons-rewards-u16-list)'),
                    (3, 8, 'groupStatIndex', 'nested(codec.seasons-rewards-u16-list)'),
                    (4, 16, 'groupStatValue', 'nested(codec.seasons-rewards-u32-list)'),
                )),
            ),
        },
    },
    'codec.seasons-rewards-u16-list': {
        'name': 'SeasonsRewardsU16List',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(u16be)'),
        ),
    },
    'codec.seasons-rewards-u32-list': {
        'name': 'SeasonsRewardsU32List',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(u32be)'),
        ),
    },
    'codec.seasons-rewards-u64-list': {
        'name': 'SeasonsRewardsU64List',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(u64be)'),
        ),
    },
    'codec.seasons-rewards-u8': {
        'name': 'SeasonsRewardsU8',
        'fields': (
            ('value', 'u8'),
        ),
    },
    'codec.seasons-rewards-u8-list': {
        'name': 'SeasonsRewardsU8List',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(nested(codec.seasons-rewards-u8))'),
        ),
    },
    'codec.social-replicated-state': {
        'name': 'SocialReplicatedState',
        'fields': (
            ('lastDailyResetTime', 'u64be'),
            ('friends', 'nested(codec.social-string-set)'),
            ('friendInvites', 'nested(codec.social-string-set)'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (1, 2, (
                    (3, 8, 'lastDailyResetTime', 'u64be'),
                    (4, 16, 'friends', 'nested(codec.social-string-set)'),
                    (5, 32, 'friendInvites', 'nested(codec.social-string-set)'),
                )),
            ),
        },
    },
    'codec.social-string': {
        'name': 'SocialString',
        'fields': (
            ('value', 'prefixed_string'),
        ),
    },
    'codec.social-string-set': {
        'name': 'SocialStringSet',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(nested(codec.social-string))'),
        ),
    },
    'codec.status-effects-component-replicated-state': {
        'name': 'StatusEffectsComponentReplicatedState',
        'fields': (
            ('m_lightweightLocalEffectsMap', 'nested(codec.status-effects-entries)'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (1, 2, (
                    (1, 2, 'm_lightweightLocalEffectsMap', 'nested(codec.status-effects-entries)'),
                )),
            ),
        },
    },
    'codec.status-effects-entries': {
        'name': 'StatusEffectsEntries',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(nested(codec.status-effects-entry))'),
        ),
    },
    'codec.status-effects-entry': {
        'name': 'StatusEffectsEntry',
        'fields': (
            ('u16_a00', 'u16be'),
            ('u64_a08', 'u64be'),
        ),
    },
    'codec.transmog-appearance': {
        'name': 'TransmogAppearance',
        'fields': (
            ('id', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('value', 'u64be'),
        ),
    },
    'codec.transmog-appearance-list': {
        'name': 'TransmogAppearanceList',
        'fields': (
            ('deltaCount', 'prefix_varint'),
            ('delta', 'optional(prefix_varint)'),
            ('elements', 'counted(u64be)'),
        ),
    },
    'codec.transmog-appearance-map': {
        'name': 'TransmogAppearanceMap',
        'fields': (
            ('elements', 'masked_counted(nested(codec.transmog-appearance))'),
        ),
    },
    'codec.transmog-inventory-ready': {
        'name': 'TransmogInventoryReady',
        'fields': (
            ('ready', 'bool_byte'),
        ),
    },
    'codec.transmog-replicated-state': {
        'name': 'TransmogComponentReplicatedState',
        'fields': (
            ('capturedArmorAppearances', 'nested(codec.transmog-appearance-map)'),
            ('capturedWeaponAppearances', 'nested(codec.transmog-appearance-list)'),
            ('ownedArmorAppearances', 'nested(codec.transmog-appearance-map)'),
            ('ownedWeaponAppearances', 'nested(codec.transmog-appearance-map)'),
            ('inventoryServicesReady', 'nested(codec.transmog-inventory-ready)'),
        ),
        'presence': {
            'group': ('group_mask', 8, None, False),
            'member': ('entry_mask', 7, 128, False),
            'groups': (
                (0, 1, (
                    (0, 1, 'capturedArmorAppearances', 'nested(codec.transmog-appearance-map)'),
                    (1, 2, 'capturedWeaponAppearances', 'nested(codec.transmog-appearance-list)'),
                    (2, 4, 'ownedArmorAppearances', 'nested(codec.transmog-appearance-map)'),
                    (3, 8, 'ownedWeaponAppearances', 'nested(codec.transmog-appearance-map)'),
                    (4, 16, 'inventoryServicesReady', 'nested(codec.transmog-inventory-ready)'),
                )),
            ),
        },
    },
}
