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
    values = {}
    cursor = offset
    for name, type_name in spec["fields"]:
        values[name], cursor = decode_field(type_name, body, cursor)
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
    out = bytearray()
    for name, type_name in spec["fields"]:
        if name not in message:
            raise WireCodecError(f"wire {wire}: missing field {name!r}")
        out += encode_field(type_name, message[name])
    return bytes(out)


def decode_codec(uid, body, *, require_full=True):
    """Decode a named nested sub-codec (not a message) into {field_name: value}."""
    spec = CODECS.get(uid)
    if spec is None:
        raise WireCodecError(f"no card-derived codec for {uid}")
    values = {}
    cursor = 0
    for name, type_name in spec["fields"]:
        values[name], cursor = decode_field(type_name, body, cursor)
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
    out = bytearray()
    for name, type_name in spec["fields"]:
        if name not in message:
            raise WireCodecError(f"codec {uid}: missing field {name!r}")
        out += encode_field(type_name, message[name])
    return bytes(out)


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
    1502: {
        'uid': 'msg.request-spend-attribute-points',
        'name': 'AttributeComponentServerFacet_RequestSpendAttributePoints',
        'direction': 'C2S',
        'fields': (
            ('field_a', 'u64be'),
            ('field_b', 'u64be'),
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
    3895: {
        'uid': 'msg.server-equip-item',
        'name': 'PaperdollComponentServerFacet_ServerEquipItem',
        'direction': 'C2S',
        'fields': (
            ('field_a', 'u64be'),
            ('field_b', 'u64be'),
            ('field_c', 'u32be'),
            ('field_d', 'u32be'),
            ('field_e', 'u32be'),
            ('field_f', 'guid16'),
            ('field_g', 'bool_byte'),
        ),
    },
}

# --- card-derived nested sub-codecs (not messages) ---
CODECS = {
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
}
