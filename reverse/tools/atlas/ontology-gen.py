#!/usr/bin/env python3
"""Derive wire code and a meanings table from the Atlas ontology cards.

WHAT THIS DOES
==============
Reads `research/atlas/ontology/schema.json` (the closed codec vocabulary) plus
every card in `research/atlas/ontology/concepts/`, and emits into
`research/generated/`:

  - `wire.py`            a table-driven encoder/decoder whose per-message field
                         layouts are DERIVED from the cards, never hand-written.
                         It imports the measured prefix-varint primitive from
                         `services/world/src/azoth_world/javelin/varint.py`
                         rather than reimplementing it.
  - `wire.rs`            the compiling Rust codec: one typed struct per ready
                         card, with `decode`/`encode`. The SAME text is written
                         into `server/crates/everfall-wire/src/generated/mod.rs`,
                         so the reviewed artifact and the crate cannot drift.
  - `meanings-table.md`  the human-readable rendering: one section per card, one
                         row per field (name, type, offset, evidence, meaning,
                         note), so the known / layout-only split is auditable.

MEANING VISIBILITY
==================
Every field declares `meaning`: `known` or `layout-only`. This is visibility,
never a gate: a `layout-only` field still emits its codec unchanged, because the
layout is known even when the meaning is not. A `layout-only` field's Rust field
doc comment says its meaning is unnamed; the field's type and the struct's
behaviour are untouched.

THE GATE
========
A card is codegen-ready only when it models at least one field, none of its
fields is `opaque(...)` or `where: memory`, every field's evidence is known, the
card's own status is not `unknown`, and every field type is a closed-vocabulary
codec. A card that is not ready is REFUSED: its wire code is not emitted (never a
partial struct), but its markdown rows still are, and the reason is printed. A
card with no `fields[]` is neither emitted nor refused; it is reported as
field-less.

DETERMINISM
===========
Output is a pure function of the schema and the cards: cards are read in sorted
filename order, the message table is sorted by wire id, no timestamps or
absolute paths are embedded, and files are written with `\\n`. Two runs therefore
produce byte-identical artifacts.

Usage:
    python ef.py re ontology-gen
    python reverse/tools/atlas/ontology-gen.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY = ROOT / "research" / "atlas" / "ontology"
SCHEMA = ONTOLOGY / "schema.json"
CONCEPTS = ONTOLOGY / "concepts"
OUT = ROOT / "research" / "generated"
WIRE_RS_CRATE = (
    ROOT / "server" / "crates" / "everfall-wire" / "src" / "generated" / "mod.rs"
)

ARTIFACTS = ("wire.py", "wire.rs", "meanings-table.md")

# The crate edition the emitted Rust is formatted for. It matches
# `server/Cargo.toml`; keeping it here lets the generator hand rustfmt the same
# edition cargo does.
CRATE_EDITION = "2024"

_DEFAULT_VOCAB: tuple[list[str], list[str]] | None = None


# --- the closed vocabulary, read from the schema ------------------------------


def load_vocabulary(schema: dict) -> tuple[list[str], list[str]]:
    """The closed codec vocabulary, declared once in schema.json `$defs.codec`.

    Returns (enum members in declared order, regex patterns). Reading it here
    rather than hard-coding it keeps the vocabulary in one place: a card type
    that the schema does not list is refused, not silently accepted.
    """
    codec = schema["$defs"]["codec"]
    members: list[str] = []
    patterns: list[str] = []
    for alternative in codec["oneOf"]:
        if "enum" in alternative:
            for member in alternative["enum"]:
                if member not in members:
                    members.append(member)
        elif "pattern" in alternative:
            patterns.append(alternative["pattern"])
    return members, patterns


def _default_vocabulary() -> tuple[list[str], list[str]]:
    global _DEFAULT_VOCAB
    if _DEFAULT_VOCAB is None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        _DEFAULT_VOCAB = load_vocabulary(schema)
    return _DEFAULT_VOCAB


def _is_vocabulary(type_name: object, members: list[str], patterns: list[str]) -> bool:
    if not isinstance(type_name, str):
        return False
    if type_name in members:
        return True
    return any(re.fullmatch(pattern, type_name) for pattern in patterns)


_VEC_TYPE = re.compile(r"^vec<.+>$")
_NESTED_REF = re.compile(r"nested\(([^()]*)\)")


def _nested_refs(type_name: object) -> list[str]:
    """Every card uid a field type names as a nested record."""
    return [match.group(1) for match in _NESTED_REF.finditer(str(type_name))]


def _container_element(type_name: str) -> str | None:
    """The element codec of a counted(...)/optional(...) container, or None."""
    for pattern in (r"^counted\((.+)\)$", r"^optional\((.+)\)$"):
        match = re.match(pattern, type_name)
        if match:
            return match.group(1)
    return None


def _field_codec(field: dict) -> str:
    """The generated type token for one card field.

    A `vec<T>` with a LITERAL integer `count` is a fixed-length run with no
    length prefix; the generated engine writes that as `vec<T>[N]`. A `count`
    of `"prefix_varint"` (or none) keeps the prefix-counted form, and every
    other type is passed through unchanged.
    """
    type_name = field["type"]
    count = field.get("count")
    if (
        isinstance(count, int)
        and not isinstance(count, bool)
        and _VEC_TYPE.match(type_name)
    ):
        return f"{type_name}[{count}]"
    return type_name


# --- the gate -----------------------------------------------------------------


def _name_list(names: list[str], cap: int = 4) -> str:
    shown = names[:cap]
    text = ", ".join(shown)
    if len(names) > cap:
        text += f" (+{len(names) - cap} more)"
    return text


def classify(
    card: dict,
    vocabulary: tuple[list[str], list[str]] | None = None,
    codecs: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Return (status, reasons) where status is ready | refused | field-less.

    ``codecs`` is the set of card uids that are themselves emitted as nested
    sub-codecs. A card that names a record outside that set is refused: the
    generated type it would point at does not exist.
    """
    fields = card.get("fields") or []
    if not fields:
        return "field-less", []

    members, patterns = vocabulary if vocabulary else _default_vocabulary()
    opaque: list[str] = []
    memory: list[str] = []
    unknown_evidence: list[str] = []
    off_vocabulary: list[str] = []
    unmasked: list[str] = []
    unresolved: list[str] = []
    bad_element: list[str] = []
    bad_member: list[str] = []
    reasons: list[str] = []
    if card.get("status") == "unknown":
        reasons.append("card status is 'unknown'")
    masked = isinstance(card.get("presence"), dict)
    for field in fields:
        name = field.get("name")
        type_name = field.get("type")
        if field.get("where", "wire") != "wire":
            memory.append(name)
        if isinstance(type_name, str) and type_name.startswith("opaque("):
            opaque.append(name)
        elif not _is_vocabulary(type_name, members, patterns):
            off_vocabulary.append(f"{name} ({type_name})")
        if field.get("evidence") == "unknown":
            unknown_evidence.append(name)
        if "presence" in field and not masked:
            unmasked.append(name)
        if masked and "presence" in field and not _member_ok(type_name):
            bad_member.append(f"{name} ({type_name})")
        element = _container_element(type_name)
        if element is not None and not _element_ok(element):
            bad_element.append(f"{name} ({type_name})")
        if codecs is not None:
            unresolved.extend(
                uid for uid in _nested_refs(type_name) if uid not in codecs
            )
    if opaque:
        reasons.append(f"opaque fields: {_name_list(opaque)}")
    if memory:
        reasons.append(f"memory (decoded-struct) fields: {_name_list(memory)}")
    if unknown_evidence:
        reasons.append(f"unknown field evidence: {_name_list(unknown_evidence)}")
    if off_vocabulary:
        reasons.append(
            f"types outside the closed vocabulary: {_name_list(off_vocabulary)}"
        )
    if unmasked:
        reasons.append(
            f"presence coordinates on a card with no two-level mask: "
            f"{_name_list(unmasked)}"
        )
    if unresolved:
        reasons.append(f"unresolved nested records: {_name_list(unresolved)}")
    if bad_element:
        reasons.append(
            f"counted/optional elements with no element layout: {_name_list(bad_element)}"
        )
    if bad_member:
        reasons.append(
            f"masked members with no member layout: "
            f"{_name_list(bad_member)}"
        )
    if reasons:
        return "refused", reasons
    return "ready", []


# --- generated Python ---------------------------------------------------------

_WIRE_PY_HEADER = '''\
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
'''

_WIRE_PY_ENGINE = r'''

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


def _decode_members(spec, data, offset):
    """Decode one record: a flat field list, or a two-level presence mask."""
    presence = spec.get("presence")
    if presence is None:
        values = {}
        for name, type_name in spec["fields"]:
            values[name], offset = decode_field(type_name, data, offset)
        return values, offset

    group_name, _group_bits, _group_continuation = presence["group"]
    member_name, member_bits, continuation = presence["member"]
    values = {}
    group_mask, offset = decode_field("u8", data, offset)
    declared = 0
    for _index, bits, _members in presence["groups"]:
        declared |= bits
    unknown = group_mask & ~declared & 0xFF
    if unknown:
        raise WireCodecError(
            f"{group_name} bit {_lowest_bit(unknown)} names no declared group"
        )
    values[group_name] = group_mask
    groups = []
    for _index, bits, members in presence["groups"]:
        if not group_mask & bits:
            continue
        entry_mask, offset = decode_field("u8", data, offset)
        if continuation is not None and entry_mask & continuation:
            raise WireCodecError(
                f"{member_name} asks for a further mask byte, which the card "
                f"does not model"
            )
        declared_members = 0
        for _member, member_bit, _name, _codec in members:
            declared_members |= member_bit
        unknown = entry_mask & ~declared_members & ~(continuation or 0) & 0xFF
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

    group_name = presence["group"][0]
    member_name = presence["member"][0]
    group_mask = values[group_name]
    out = bytearray(encode_field("u8", group_mask))
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
        out += encode_field("u8", entry_mask)
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
'''


def _presence_spec(card: dict, fields: list[dict]) -> dict | None:
    """The card's two-level presence mask, or None for a flat record.

    Groups and members are sorted here, once, so both emitters read a body in the
    one order the client's reader uses: ascending group index, then ascending
    member index. Nothing in this function knows which card it is reading.
    """
    declared = card.get("presence")
    if not isinstance(declared, dict):
        return None
    grouped: dict[int, list[dict]] = {}
    for field in fields:
        coords = field.get("presence") or {}
        member = int(coords.get("member", 0))
        grouped.setdefault(int(coords.get("group", 0)), []).append(
            {**field, "index": member, "bit": 1 << member}
        )
    groups = []
    for index in sorted(grouped):
        members = []
        for field in sorted(grouped[index], key=lambda member: member["index"]):
            members.append(
                {
                    "index": field["index"],
                    "bit": field["bit"],
                    "name": field["name"],
                    "codec": field["codec"],
                    "id": field["id"],
                    "max": field.get("max"),
                    "meaning": field.get("meaning", "known"),
                }
            )
        groups.append({"index": index, "bit": 1 << index, "members": members})
    return {
        "group": {
            "name": declared["group"]["name"],
            "bits": declared["group"]["bits"],
            "continuation": declared["group"].get("continuation"),
        },
        "member": {
            "name": declared["member"]["name"],
            "bits": declared["member"]["bits"],
            "continuation": declared["member"].get("continuation"),
        },
        "groups": groups,
    }


def _render_presence_py(presence: dict, indent: str) -> list[str]:
    """The emitted Python form of one card's two-level presence mask."""
    group = presence["group"]
    member = presence["member"]
    lines = [f"{indent}'presence': {{"]
    lines.append(
        f"{indent}    'group': ({group['name']!r}, {group['bits']}, "
        f"{group['continuation']}),"
    )
    lines.append(
        f"{indent}    'member': ({member['name']!r}, {member['bits']}, "
        f"{member['continuation']}),"
    )
    lines.append(f"{indent}    'groups': (")
    for declared in presence["groups"]:
        lines.append(f"{indent}        ({declared['index']}, {declared['bit']}, (")
        for field in declared["members"]:
            lines.append(
                f"{indent}            ({field['index']}, {field['bit']}, "
                f"{field['name']!r}, {field['codec']!r}),"
            )
        lines.append(f"{indent}        )),")
    lines.append(f"{indent}    ),")
    lines.append(f"{indent}}},")
    return lines


def render_wire_py(
    members: list[str], patterns: list[str], messages: list[dict], codecs: list[dict]
) -> str:
    lines = [_WIRE_PY_HEADER, "", "# The closed vocabulary, from schema.json $defs.codec."]
    lines.append("VOCABULARY = (")
    for member in members:
        lines.append(f"    {member!r},")
    lines.append(")")
    lines.append("CODEC_PATTERNS = (")
    for pattern in patterns:
        lines.append(f"    {pattern!r},")
    lines.append(")")
    lines.append(_WIRE_PY_ENGINE)
    lines.append("")
    lines.append("# --- card-derived message layouts (BODY fields only) ---")
    lines.append("MESSAGES = {")
    for spec in messages:
        lines.append(f"    {spec['wire_id']}: {{")
        lines.append(f"        'uid': {spec['uid']!r},")
        lines.append(f"        'name': {spec['name']!r},")
        lines.append(f"        'direction': {spec['direction']!r},")
        lines.append("        'fields': (")
        for field in spec["fields"]:
            lines.append(f"            ({field['name']!r}, {field['codec']!r}),")
        lines.append("        ),")
        if spec.get("presence"):
            lines.extend(_render_presence_py(spec["presence"], "        "))
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("# --- card-derived nested sub-codecs (not messages) ---")
    lines.append("CODECS = {")
    for spec in codecs:
        lines.append(f"    {spec['uid']!r}: {{")
        lines.append(f"        'name': {spec['name']!r},")
        lines.append("        'fields': (")
        for field in spec["fields"]:
            lines.append(f"            ({field['name']!r}, {field['codec']!r}),")
        lines.append("        ),")
        if spec.get("presence"):
            lines.extend(_render_presence_py(spec["presence"], "        "))
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


# --- generated Rust ------------------------------------------------------------

_RUST_RS_HEADER = '''\
// GENERATED FILE -- do not edit by hand.
//!
//! Typed messages and nested sub-codecs derived from the Atlas cards.
//!
//! Produced by `reverse/tools/atlas/ontology-gen.py` (`python ef.py re
//! ontology-gen`) from `research/atlas/ontology/schema.json` and the Atlas
//! concept cards. One struct per codegen-ready card: its fields are that card's
//! body fields under the card's own names, and a raw byte run is an [`Opaque`]
//! that carries its Atlas id.
//!
//! This exact text is written to
//! `server/crates/everfall-wire/src/generated/mod.rs` and mirrored here for
//! review. The record envelope (`00 01` plus the prefix-varint type) is framing
//! owned by `crate::framing` and is never a field.

use crate::framing::{Reader, Writer, WireError};
use crate::opaque::Opaque;
'''

# codec token -> (Rust type, Reader method, Writer method, zero literal,
#                 writer-fallible, is-float)
_RUST_SCALARS: dict[str, tuple[str, str, str, str, bool, bool]] = {
    "u8": ("u8", "u8", "u8", "0", False, False),
    "i8": ("i8", "i8", "i8", "0", False, False),
    "u16be": ("u16", "u16be", "u16be", "0", False, False),
    "u16le": ("u16", "u16le", "u16le", "0", False, False),
    "i16be": ("i16", "i16be", "i16be", "0", False, False),
    "u32be": ("u32", "u32be", "u32be", "0", False, False),
    "u32le": ("u32", "u32le", "u32le", "0", False, False),
    "i32be": ("i32", "i32be", "i32be", "0", False, False),
    "u64be": ("u64", "u64be", "u64be", "0", False, False),
    "u64le": ("u64", "u64le", "u64le", "0", False, False),
    "i64be": ("i64", "i64be", "i64be", "0", False, False),
    "f32be": ("f32", "f32be", "f32be", "0.0", False, True),
    "f32le": ("f32", "f32le", "f32le", "0.0", False, True),
    "f64be": ("f64", "f64be", "f64be", "0.0", False, True),
    "enum8": ("u8", "u8", "u8", "0", False, False),
    "enum16be": ("u16", "u16be", "u16be", "0", False, False),
    "enum32be": ("u32", "u32be", "u32be", "0", False, False),
    "bitset8": ("u8", "u8", "u8", "0", False, False),
    "bitset16": ("u16", "u16be", "u16be", "0", False, False),
    "bitset32be": ("u32", "u32be", "u32be", "0", False, False),
    "prefix_varint": ("u64", "prefix_varint", "prefix_varint", "0", True, False),
    "varint": ("u64", "varint", "varint", "0", False, False),
    "bool_byte": ("bool", "bool_byte", "u8", "false", False, False),
}

_RUST_KEYWORDS = frozenset(
    """
    as break const continue crate dyn else enum extern false fn for if impl in let
    loop match mod move mut pub ref return self Self static struct super trait true
    type unsafe use where while async await
    """.split()
)

_RUST_FIXED = re.compile(r"^(bytes|fixed_string)\(([0-9]+)\)$")
_RUST_VEC_LITERAL = re.compile(r"^vec<(.+)>\[([0-9]+)\]$")
_RUST_VEC = re.compile(r"^vec<(.+)>$")
_RUST_MATRIX = re.compile(r"^matrix<(.+)>$")
_RUST_NESTED = re.compile(r"^nested\((.+)\)$")
_RUST_COUNTED = re.compile(r"^counted\((.+)\)$")
_RUST_OPTIONAL = re.compile(r"^optional\((.+)\)$")


def rust_type_name(uid: str) -> str:
    """A deterministic PascalCase Rust type name for one card uid."""
    parts = re.split(r"[.\-]", uid)
    name = "".join(part[:1].upper() + part[1:] for part in parts if part)
    if not name or name[0].isdigit():
        name = "Card" + name
    if name in _RUST_KEYWORDS:
        name += "Msg"
    return name


def rust_field_name(name: str) -> str:
    """A valid snake_case Rust field name for one card field name.

    A card names a field the way the client's own reflection string does
    (`someField`); Rust wants `some_field`, so the camel-case
    boundary becomes an underscore.
    """
    ident = re.sub(r"[^0-9A-Za-z_]", "_", name)
    ident = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", ident).lower()
    if not ident or ident[0].isdigit():
        ident = "f_" + ident
    if ident in _RUST_KEYWORDS:
        ident += "_"
    return ident


def _rust_write(write: str, expr: str, fallible: bool, element: str) -> str:
    """One `writer.<write>(<expr>);` line, widening a bool to its byte."""
    if element == "bool_byte":
        expr = f"u8::from({expr})"
    call = f"writer.{write}({expr})"
    return call + "?;" if fallible else call + ";"


def rust_variant_name(name: str) -> str:
    """A deterministic PascalCase enum variant name for one presence member."""
    parts = re.findall(r"[A-Za-z0-9]+", name)
    variant = "".join(part[:1].upper() + part[1:] for part in parts)
    if not variant or variant[0].isdigit():
        variant = "Member" + variant
    if variant in _RUST_KEYWORDS:
        variant += "Member"
    return variant


def _rust_element(
    codec: str, name: str, atlas_id: str
) -> tuple[str, str, str, bool]:
    """(Rust type, read expression, write template, needs a deref) for one element.

    An element is what a counted container, an optional or a presence member
    carries: a scalar, a string, a raw run, or `nested(<uid>)`, whose value is
    another card's generated body. A container element is expressed by naming a
    nested record card, never by nesting one container inside another.
    """
    if codec in _RUST_SCALARS:
        rust_type, read, write, _zero, fallible, _is_float = _RUST_SCALARS[codec]
        if codec == "bool_byte":
            return (
                rust_type,
                f'reader.bool_byte("{name}")?',
                "writer.u8(u8::from({}));",
                True,
            )
        suffix = "?;" if fallible else ";"
        return (
            rust_type,
            f'reader.{read}("{name}")?',
            f"writer.{write}({{}}){suffix}",
            True,
        )
    match = _RUST_NESTED.match(codec)
    if match:
        nested = rust_type_name(match.group(1))
        return nested, f"{nested}::read_from(reader)?", "{}.write_to(writer)?;", False
    match = _RUST_FIXED.match(codec)
    if match:
        kind, width = match.group(1), int(match.group(2))
        if kind == "bytes":
            return (
                "Opaque",
                f'reader.opaque("{name}", "{atlas_id}", {width})?',
                "writer.opaque({});",
                False,
            )
        return (
            "String",
            f'reader.fixed_string("{name}", {width})?',
            f"writer.fixed_string({{}}, {width})?;",
            False,
        )
    if codec == "guid16":
        return (
            "Opaque",
            f'reader.opaque("{name}", "{atlas_id}", 16)?',
            "writer.opaque({});",
            False,
        )
    if codec == "prefixed_string":
        return "String", f'reader.prefixed_string("{name}")?', "writer.prefixed_string({})?;", False
    if codec == "prefixed_bytes":
        return (
            "Opaque",
            f'reader.prefixed_opaque("{name}", "{atlas_id}")?',
            "writer.prefixed_opaque({})?;",
            False,
        )
    raise ValueError(f"codec {codec!r} cannot be a counted, optional or masked element")


def _element_ok(codec: object) -> bool:
    """True when one codec can be a counted/optional element."""
    try:
        _rust_element(str(codec), "x", "x.x")
    except ValueError:
        return False
    return True


def _rust_member(
    codec: str, name: str, atlas_id: str, maximum: int | None
) -> tuple[str, list[str], list[str]]:
    """(Rust type, decode lines, encode lines) for one presence-masked member.

    The decode lines bind a local `value`; the encode lines write a `&value`
    binding, which is what an enum match arm hands them. A member may be one
    value, a counted container with its own element layout, or an optional, so a
    two-level mask composes with the other constructs instead of needing a
    wrapper card for every member.
    """
    match = _RUST_COUNTED.match(codec) or _RUST_VEC.match(codec)
    if match:
        element = match.group(1)
        rust_type, read, write, deref = _rust_element(element, name, atlas_id)
        decode = [f'let count = reader.prefix_varint("{name}")?;']
        if maximum is not None:
            decode.append(
                f'if count > {maximum} {{ return Err(WireError::OutOfRange '
                f'{{ field: "{name}", max: {maximum}, value: count }}); }}'
            )
        decode.extend(
            [
                'let mut value = Vec::new();',
                'for _ in 0..count {',
                f'    value.push({read});',
                '}',
            ]
        )
        encode = [
            'writer.prefix_varint(value.len() as u64)?;',
            'for item in value {',
            '    ' + write.format("*item" if deref else "item"),
            '}',
        ]
        return f"Vec<{rust_type}>", decode, encode
    match = _RUST_OPTIONAL.match(codec)
    if match:
        element = match.group(1)
        rust_type, read, write, deref = _rust_element(element, name, atlas_id)
        decode = [
            f'let flag = reader.u8("{name}")?;',
            'if flag > 1 {',
            f'    return Err(WireError::NotBoolean {{ field: "{name}", value: flag }});',
            '}',
            'let value = if flag == 1 {',
            f'    Some({read})',
            '} else {',
            '    None',
            '};',
        ]
        encode = [
            'match value {',
            '    Some(inner) => {',
            '        writer.u8(1);',
            '        ' + write.format("*inner" if deref else "inner"),
            '    }',
            '    None => {',
            '        writer.u8(0);',
            '    }',
            '}',
        ]
        return f"Option<{rust_type}>", decode, encode
    rust_type, read, write, deref = _rust_element(codec, name, atlas_id)
    return (
        rust_type,
        [f'let value = {read};'],
        [write.format("*value" if deref else "value")],
    )


def _member_ok(codec: object) -> bool:
    """True when one codec can be a presence-masked member."""
    try:
        _rust_member(str(codec), "x", "x.x", None)
    except ValueError:
        return False
    return True


def _rust_field(field: dict) -> dict:
    """Render one card field to its Rust type, value expression, and writes.

    `decode` is a LIST of lines whose last line is the expression the field's
    value evaluates to, so `read_from` can assemble the whole body as one struct
    literal with a block per field. Binding one local per field instead would put
    a card's measured offset names (`u64_a10`, `u32_a1c`) in one scope, where
    `clippy::similar_names` is right to complain about them.
    """
    name = field["name"]
    codec = field["codec"]
    ident = rust_field_name(name)
    atlas_id = field["id"]
    maximum = field.get("max")
    result: dict = {
        "name": name,
        "codec": codec,
        "ident": ident,
        "meaning": field.get("meaning", "known"),
        "rust_type": "",
        "decode": [],
        "encode": [],
        "is_float": False,
    }
    if codec == "bool_byte":
        result["rust_type"] = "bool"
        result["decode"] = [f'reader.bool_byte("{name}")?']
        result["encode"] = [f"writer.u8(u8::from(self.{ident}));"]
        return result
    if codec in _RUST_SCALARS:
        rust_type, read, write, _zero, fallible, is_float = _RUST_SCALARS[codec]
        result["rust_type"] = rust_type
        result["is_float"] = is_float
        if maximum is not None and codec == "prefix_varint":
            result["decode"] = [
                f'let value = reader.prefix_varint("{name}")?;',
                f"if value > {maximum} {{",
                "    return Err(WireError::OutOfRange {",
                f'        field: "{name}",',
                f"        max: {maximum},",
                "        value,",
                "    });",
                "}",
                "value",
            ]
        else:
            result["decode"] = [f'reader.{read}("{name}")?']
        result["encode"] = [_rust_write(write, f"self.{ident}", fallible, codec)]
        return result
    if codec == "prefixed_string":
        result["rust_type"] = "String"
        result["decode"] = [f'reader.prefixed_string("{name}")?']
        result["encode"] = [f"writer.prefixed_string(&self.{ident})?;"]
        return result
    match = _RUST_FIXED.match(codec)
    if match:
        kind, width = match.group(1), int(match.group(2))
        if kind == "bytes":
            result["rust_type"] = "Opaque"
            result["decode"] = [f'reader.opaque("{name}", "{atlas_id}", {width})?']
            result["encode"] = [f"writer.opaque(&self.{ident});"]
        else:
            result["rust_type"] = "String"
            result["decode"] = [f'reader.fixed_string("{name}", {width})?']
            result["encode"] = [f"writer.fixed_string(&self.{ident}, {width})?;"]
        return result
    if codec == "prefixed_bytes":
        result["rust_type"] = "Opaque"
        result["decode"] = [f'reader.prefixed_opaque("{name}", "{atlas_id}")?']
        if maximum is not None:
            result["decode"] = [
                f'let value = reader.prefixed_opaque("{name}", "{atlas_id}")?;',
                f"if value.len() as u64 > {maximum} {{",
                "    return Err(WireError::OutOfRange {",
                f'        field: "{name}",',
                f"        max: {maximum},",
                "        value: value.len() as u64,",
                "    });",
                "}",
                "value",
            ]
        result["encode"] = [f"writer.prefixed_opaque(&self.{ident})?;"]
        return result
    if codec == "guid16":
        result["rust_type"] = "Opaque"
        result["decode"] = [f'reader.opaque("{name}", "{atlas_id}", 16)?']
        result["encode"] = [f"writer.opaque(&self.{ident});"]
        return result
    match = _RUST_NESTED.match(codec)
    if match:
        # A nested record: the value is another card's generated body, so its
        # layout is named once and never copied into this card.
        nested = rust_type_name(match.group(1))
        result["rust_type"] = nested
        result["decode"] = [f"{nested}::read_from(reader)?"]
        result["encode"] = [f"self.{ident}.write_to(writer)?;"]
        return result
    match = _RUST_COUNTED.match(codec) or _RUST_VEC.match(codec)
    if match:
        element = match.group(1)
        rust_type, read, write, deref = _rust_element(element, name, atlas_id)
        result["rust_type"] = f"Vec<{rust_type}>"
        result["is_float"] = element in {"f32be", "f32le", "f64be"}
        decode = [f'let count = reader.prefix_varint("{name}")?;']
        if maximum is not None:
            decode.extend(
                [
                    f"if count > {maximum} {{",
                    "    return Err(WireError::OutOfRange {",
                    f'        field: "{name}",',
                    f"        max: {maximum},",
                    "        value: count,",
                    "    });",
                    "}",
                ]
            )
        decode.extend(
            [
                "let mut value = Vec::new();",
                "for _ in 0..count {",
                f"    value.push({read});",
                "}",
                "value",
            ]
        )
        result["decode"] = decode
        argument = "*value" if deref else "value"
        result["encode"] = [
            f"writer.prefix_varint(self.{ident}.len() as u64)?;",
            f"for value in &self.{ident} {{",
            "    " + write.format(argument),
            "}",
        ]
        return result
    match = _RUST_OPTIONAL.match(codec)
    if match:
        # A value behind a STRICT zero-or-one flag byte: any other flag is
        # refused instead of being read as true.
        element = match.group(1)
        rust_type, read, write, deref = _rust_element(element, name, atlas_id)
        result["rust_type"] = f"Option<{rust_type}>"
        result["decode"] = [
            f'let flag = reader.u8("{name}")?;',
            "if flag > 1 {",
            "    return Err(WireError::NotBoolean {",
            f'        field: "{name}",',
            "        value: flag,",
            "    });",
            "}",
            "if flag == 1 {",
            f"    Some({read})",
            "} else {",
            "    None",
            "}",
        ]
        argument = "*value" if deref else "value"
        result["encode"] = [
            f"match &self.{ident} {{",
            "    Some(value) => {",
            "        writer.u8(1);",
            "        " + write.format(argument),
            "    }",
            "    None => {",
            "        writer.u8(0);",
            "    }",
            "}",
        ]
        return result
    match = _RUST_VEC_LITERAL.match(codec)
    if match:
        element, count = match.group(1), int(match.group(2))
        rust_type, read, write, zero, fallible, is_float = _RUST_SCALARS[element]
        result["rust_type"] = f"[{rust_type}; {count}]"
        result["is_float"] = is_float
        result["decode"] = [
            f"let mut value = [{zero}; {count}];",
            "for slot in &mut value {",
            f'    *slot = reader.{read}("{name}")?;',
            "}",
            "value",
        ]
        result["encode"] = [
            f"for value in &self.{ident} {{",
            "    " + _rust_write(write, "*value", fallible, element),
            "}",
        ]
        return result
    match = _RUST_MATRIX.match(codec)
    if match:
        element = match.group(1)
        rust_type, read, write, _zero, fallible, is_float = _RUST_SCALARS[element]
        result["rust_type"] = f"Vec<Vec<{rust_type}>>"
        result["is_float"] = is_float
        decode = [f'let rows = reader.prefix_varint("{name}")?;']
        if maximum is not None:
            decode.append(
                f"if rows > {maximum} {{ return Err(WireError::OutOfRange "
                f'{{ field: "{name}", max: {maximum}, value: rows }}); }}'
            )
        decode.append(f'let cols = reader.prefix_varint("{name}")?;')
        decode.extend(
            [
                "let mut value = Vec::new();",
                "for _ in 0..rows {",
                "    let mut row = Vec::new();",
                "    for _ in 0..cols {",
                f'        row.push(reader.{read}("{name}")?);',
                "    }",
                "    value.push(row);",
                "}",
                "value",
            ]
        )
        result["decode"] = decode
        result["encode"] = [
            f"writer.prefix_varint(self.{ident}.len() as u64)?;",
            f"let cols = self.{ident}.first().map_or(0, Vec::len);",
            "writer.prefix_varint(cols as u64)?;",
            f"for row in &self.{ident} {{",
            "    for value in row {",
            "        " + _rust_write(write, "*value", fallible, element),
            "    }",
            "}",
        ]
        return result
    raise ValueError(f"codec {codec!r} cannot be rendered to Rust")


def _render_card(spec: dict, *, wire: bool) -> list[str]:
    if spec.get("presence"):
        return _render_presence_card(spec, wire=wire)
    uid = spec["uid"]
    type_name = rust_type_name(uid)
    fields = [_rust_field(field) for field in spec["fields"]]
    has_float = any(field["is_float"] for field in fields)
    bool_fields = sum(1 for field in fields if field["rust_type"] == "bool")

    lines = [f"/// `{uid}` \u2014 one Atlas card.", "///"]
    if wire:
        lines.append(f"/// Message card, wire id `{spec['wire_id']}`.")
    else:
        lines.append("/// Nested sub-codec card (no wire id).")
    if bool_fields > 3:
        lines.append(
            '#[expect(clippy::struct_excessive_bools, reason = '
            '"the card models one bool byte per trailing flag")]'
        )
    derive = "Debug, Clone, PartialEq" + ("" if has_float else ", Eq")
    lines.append(f"#[derive({derive})]")
    lines.append(f"pub struct {type_name} {{")
    for field in fields:
        doc = f"Body field `{field['name']}` (`{field['codec']}`)"
        if field["meaning"] == "layout-only":
            doc += "; meaning unnamed."
        else:
            doc += "."
        lines.append(f"    /// {doc}")
        lines.append(f"    pub {field['ident']}: {field['rust_type']},")
    lines.append("}")
    lines.append("")
    lines.append(f"impl {type_name} {{")
    lines.append("    /// The Atlas card id.")
    lines.append(f'    pub const UID: &\'static str = "{uid}";')
    if wire:
        lines.append("    /// The card wire id.")
        lines.append(f"    pub const WIRE_ID: u32 = {spec['wire_id']};")
    lines.append("")
    lines.append(f"    /// Decode one `{uid}` body.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when the body is shorter, longer, or outside")
    lines.append("    /// a bound the card states.")
    lines.append("    pub fn decode(body: &[u8]) -> Result<Self, WireError> {")
    lines.append("        let mut reader = Reader::new(body);")
    lines.append("        let value = Self::read_from(&mut reader)?;")
    lines.append("        reader.finish()?;")
    lines.append("        Ok(value)")
    lines.append("    }")
    lines.append("")
    lines.append("    /// Read one body from the middle of a larger record.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when a field is truncated or outside a bound the")
    lines.append("    /// card states.")
    lines.append(
        "    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {"
    )
    lines.append("        Ok(Self {")
    for field in fields:
        values = field["decode"]
        if len(values) == 1:
            lines.append(f"            {field['ident']}: {values[0]},")
        else:
            lines.append(f"            {field['ident']}: {{")
            lines.extend("                " + line for line in values)
            lines.append("            },")
    lines.append("        })")
    lines.append("    }")
    lines.append("")
    lines.append(f"    /// Encode one `{uid}` body, appending to `out`.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when a value exceeds a width the card states.")
    lines.append("    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {")
    lines.append("        let mut writer = Writer::new(out);")
    lines.append("        self.write_to(&mut writer)")
    lines.append("    }")
    lines.append("")
    lines.append("    /// Write one body into the middle of a larger record.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when a value exceeds a width the card states.")
    lines.append(
        "    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {"
    )
    for field in fields:
        lines.extend("        " + line for line in field["encode"])
    lines.append("        Ok(())")
    lines.append("    }")
    lines.append("}")
    return lines


def _mask_literal(value: int) -> str:
    """One mask byte as a Rust binary literal, low bit first and byte-wide.

    Always eight digits so the continuation bit (0x80) sits visibly at the left
    of a seven-bit member level.
    """
    digits = format(value, "08b")
    return "0b" + "_".join((digits[0:4], digits[4:8]))


def _render_presence_card(spec: dict, *, wire: bool) -> list[str]:
    """One card whose body is a two-level presence mask plus its present members.

    Nothing here is specific to any one component: the group and member indices,
    the mask bytes and every member's codec come from the card, so a second
    presence-masked record is the same text with different names.
    """
    uid = spec["uid"]
    presence = spec["presence"]
    base = rust_type_name(uid)
    group_type = base + "Group"
    entry_type = base + "Entry"
    group_mask_ident = rust_field_name(presence["group"]["name"])
    member_mask_ident = rust_field_name(presence["member"]["name"])
    groups = presence["groups"]
    declared_groups = 0
    members: list[dict] = []
    for declared in groups:
        declared_groups |= declared["bit"]
        for field in declared["members"]:
            rust_type, decode, encode = _rust_member(
                field["codec"], field["name"], field["id"], field.get("max")
            )
            members.append(
                {
                    **field,
                    "group": declared["index"],
                    "variant": rust_variant_name(field["name"]),
                    "rust_type": rust_type,
                    "decode": decode,
                    "encode": encode,
                }
            )
    has_float = any(
        field["codec"] in {"f32be", "f32le", "f64be"} for field in members
    )

    lines = [f"/// `{uid}` \u2014 one Atlas card.", "///"]
    if wire:
        lines.append(f"/// Message card, wire id `{spec['wire_id']}`.")
    else:
        lines.append("/// Presence-masked sub-codec card (no wire id).")
    lines.append(
        "/// Its body is a two-level presence mask: one group mask byte, then for"
    )
    lines.append(
        "/// each present group one member mask byte, then the present members'"
    )
    lines.append("/// bodies in ascending member order.")
    derive = "Debug, Clone, PartialEq" + ("" if has_float else ", Eq")
    lines.append(f"#[derive({derive})]")
    lines.append(f"pub struct {base} {{")
    lines.append(f"    /// The `{presence['group']['name']}` byte: bit i set means group i is")
    lines.append("    /// on the wire.")
    lines.append(f"    pub {group_mask_ident}: u8,")
    lines.append("    /// The present groups, ascending by group index.")
    lines.append(f"    pub groups: Vec<{group_type}>,")
    lines.append("}")
    lines.append("")
    lines.append(f"/// One present group of [`{base}`].")
    lines.append(f"#[derive({derive})]")
    lines.append(f"pub struct {group_type} {{")
    lines.append(f"    /// The `{presence['member']['name']}` byte: bit i set means member i is")
    lines.append("    /// on the wire.")
    lines.append(f"    pub {member_mask_ident}: u8,")
    lines.append("    /// The present members, ascending by member index.")
    lines.append(f"    pub entries: Vec<{entry_type}>,")
    lines.append("}")
    lines.append("")
    lines.append(f"/// One present member of a [`{group_type}`].")
    lines.append(f"#[derive({derive})]")
    lines.append(f"pub enum {entry_type} {{")
    for field in members:
        doc = f"Group {field['group']} member {field['index']}, `{field['name']}`"
        doc += " (meaning unnamed)." if field["meaning"] == "layout-only" else "."
        lines.append(f"    /// {doc}")
        lines.append(f"    {field['variant']}({field['rust_type']}),")
    lines.append("}")
    lines.append("")
    lines.append(f"impl {base} {{")
    lines.append("    /// The Atlas card id.")
    lines.append(f'    pub const UID: &\'static str = "{uid}";')
    if wire:
        lines.append("    /// The card wire id.")
        lines.append(f"    pub const WIRE_ID: u32 = {spec['wire_id']};")
    lines.append("")
    lines.append(f"    /// Decode one `{uid}` body.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when the body is shorter, longer, outside a bound")
    lines.append("    /// the card states, or its mask selects a group or member the card does")
    lines.append("    /// not declare.")
    lines.append("    pub fn decode(body: &[u8]) -> Result<Self, WireError> {")
    lines.append("        let mut reader = Reader::new(body);")
    lines.append("        let value = Self::read_from(&mut reader)?;")
    lines.append("        reader.finish()?;")
    lines.append("        Ok(value)")
    lines.append("    }")
    lines.append("")
    lines.append("    /// Read one body from the middle of a larger record.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when the body is shorter, or a mask selects a group")
    lines.append("    /// or member the card does not declare.")
    lines.append(
        "    pub fn read_from(reader: &mut Reader<'_>) -> Result<Self, WireError> {"
    )
    lines.append(f'        let {group_mask_ident} = reader.u8("{presence["group"]["name"]}")?;')
    lines.append(f"        let unknown = {group_mask_ident} & !{_mask_literal(declared_groups)};")
    lines.append("        if unknown != 0 {")
    lines.append("            return Err(WireError::UnknownPresence {")
    lines.append('                what: "group",')
    lines.append("                index: u64::from(unknown.trailing_zeros()),")
    lines.append("            });")
    lines.append("        }")
    lines.append("        let mut groups = Vec::new();")
    for declared in groups:
        declared_members = 0
        for field in declared["members"]:
            declared_members |= field["bit"]
        lines.append(
            f"        if {group_mask_ident} & {_mask_literal(declared['bit'])} != 0 {{"
        )
        lines.append(
            f'            let {member_mask_ident} = reader.u8("{presence["member"]["name"]}")?;'
        )
        lines.append(
            f"            let unknown = {member_mask_ident} & "
            f"!{_mask_literal(declared_members)};"
        )
        lines.append("            if unknown != 0 {")
        lines.append("                return Err(WireError::UnknownPresence {")
        lines.append('                    what: "member",')
        lines.append("                    index: u64::from(unknown.trailing_zeros()),")
        lines.append("                });")
        lines.append("            }")
        lines.append("            let mut entries = Vec::new();")
        for field in members:
            if field["group"] != declared["index"]:
                continue
            bit = _mask_literal(field["bit"])
            lines.append(f"            if {member_mask_ident} & {bit} != 0 {{")
            lines.extend("                " + line for line in field["decode"])
            lines.append(
                f"                entries.push({entry_type}::{field['variant']}(value));"
            )
            lines.append("            }")
        lines.append("            groups.push(" + group_type + " {")
        lines.append(f"                {member_mask_ident},")
        lines.append("                entries,")
        lines.append("            });")
        lines.append("        }")
    lines.append(f"        Ok(Self {{ {group_mask_ident}, groups }})")
    lines.append("    }")
    lines.append("")
    lines.append(f"    /// Encode one `{uid}` body, appending to `out`.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when a value exceeds a width the card states.")
    lines.append("    pub fn encode(&self, out: &mut Vec<u8>) -> Result<(), WireError> {")
    lines.append("        let mut writer = Writer::new(out);")
    lines.append("        self.write_to(&mut writer)")
    lines.append("    }")
    lines.append("")
    lines.append("    /// Write one body into the middle of a larger record.")
    lines.append("    ///")
    lines.append("    /// # Errors")
    lines.append("    /// Returns [`WireError`] when a value exceeds a width the card states.")
    lines.append(
        "    pub fn write_to(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {"
    )
    lines.append(f"        writer.u8(self.{group_mask_ident});")
    lines.append("        for group in &self.groups {")
    lines.append(f"            writer.u8(group.{member_mask_ident});")
    lines.append("            for entry in &group.entries {")
    lines.append("                match entry {")
    for field in members:
        lines.append(f"                    {entry_type}::{field['variant']}(value) => {{")
        lines.extend("                        " + line for line in field["encode"])
        lines.append("                    }")
    lines.append("                }")
    lines.append("            }")
    lines.append("        }")
    lines.append("        Ok(())")
    lines.append("    }")
    lines.append("}")
    return lines


def render_wire_rs(
    members: list[str], patterns: list[str], messages: list[dict], codecs: list[dict]
) -> str:
    lines = [_RUST_RS_HEADER]
    for spec in messages:
        lines.append("")
        lines.extend(_render_card(spec, wire=True))
    for spec in codecs:
        lines.append("")
        lines.extend(_render_card(spec, wire=False))
    return "\n".join(lines) + "\n"


# --- generated markdown -------------------------------------------------------


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_meanings_md(classifications: list[tuple[dict, str, list[str]]]) -> str:
    lines = [
        "# Meanings table (generated)",
        "",
        "> Generated by `reverse/tools/atlas/ontology-gen.py` from "
        "`research/atlas/ontology/schema.json` and the concept cards.",
        "> One section per card, one row per field. Do not edit by hand; read "
        "`research/atlas/meanings.md` for the prose tables.",
        "",
    ]
    for card, status, reasons in classifications:
        uid = card["uid"]
        wire = card.get("wire") or {}
        lines.append(f"## {uid} — {card.get('name', '')}")
        lines.append("")
        identity = []
        if wire.get("id") is not None:
            identity.append(f"wire {wire['id']}")
        if wire.get("direction"):
            identity.append(str(wire["direction"]))
        if identity:
            lines.append(f"- {', '.join(identity)}")
        lines.append(
            f"- kind: {card.get('kind')}; status: {card.get('status')}; "
            f"confidence: {card.get('confidence')}"
        )
        presence = card.get("presence")
        if isinstance(presence, dict):
            group = presence["group"]
            member = presence["member"]
            lines.append(
                "- presence: two-level mask — "
                f"group `{group['name']}` ({group['bits']} bits), "
                f"member `{member['name']}` ({member['bits']} bits"
                + (
                    f", continuation {member['continuation']}"
                    if member.get("continuation") is not None
                    else ""
                )
                + ")"
            )
            for field in card.get("fields") or []:
                coords = field.get("presence") or {}
                lines.append(
                    f"  - group {coords.get('group')} member {coords.get('member')}: "
                    f"`{field.get('name')}` (`{field.get('type')}`)"
                )
        if status == "ready":
            lines.append("- codegen: **ready** — wire code emitted")
        elif status == "refused":
            lines.append("- codegen: **refused** — " + "; ".join(reasons))
        else:
            lines.append("- codegen: field-less — neither emitted nor refused")
        lines.append("")
        fields = card.get("fields") or []
        if fields:
            lines.append("| field | type | offset | evidence | meaning | note |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for field in fields:
                lines.append(
                    "| {name} | {type} | {offset} | {evidence} | {meaning} | {note} |".format(
                        name=_cell(field.get("name")),
                        type=_cell(field.get("type")),
                        offset=_cell(field.get("offset", "—")),
                        evidence=_cell(field.get("evidence")),
                        meaning=_cell(field.get("meaning", "—")),
                        note=_cell(field.get("note", "")),
                    )
                )
            lines.append("")
    return "\n".join(lines) + "\n"


# --- driver -------------------------------------------------------------------


def generate(schema_path, concepts_dir, out_dir, crate_out=None) -> dict:
    """Emit the artifacts into ``out_dir``; return the gate report.

    When ``crate_out`` is given, the exact `wire.rs` text is also written to that
    path (normally
    ``server/crates/everfall-wire/src/generated/mod.rs``), so the reviewed
    artifact and the crate cannot drift. Tests pass no ``crate_out`` and so never
    touch the crate.
    """
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    vocabulary = load_vocabulary(schema)

    cards = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(concepts_dir).glob("*.json"))
    ]

    # A nested record must itself be emitted, so the gate runs to a fixpoint: a
    # card is ready once every record it names is. Two passes settle a tree, and
    # the loop costs nothing, so a cyclic card set is refused instead of
    # crashing.
    statuses: dict[str, tuple[str, list[str]]] = {}
    codecs_ready: set[str] = set()
    while True:
        previous = dict(statuses)
        for card in cards:
            statuses[card["uid"]] = classify(card, vocabulary, codecs_ready)
        codecs_ready = {
            card["uid"]
            for card in cards
            if statuses[card["uid"]][0] == "ready"
            and (card.get("wire") or {}).get("id") is None
        }
        if statuses == previous:
            break
    classifications: list[tuple[dict, str, list[str]]] = [
        (card, *statuses[card["uid"]]) for card in cards
    ]

    emitted: list[str] = []
    refused: list[tuple[str, str]] = []
    fieldless: list[str] = []
    messages: list[dict] = []
    codecs: list[dict] = []
    for card, status, reasons in classifications:
        if status == "ready":
            wire = card.get("wire") or {}
            fields = [
                {
                    "name": f["name"],
                    "codec": _field_codec(f),
                    "id": f"{card['uid']}.{f['name']}",
                    "max": f.get("max"),
                    "meaning": f.get("meaning", "known"),
                    "presence": f.get("presence"),
                }
                for f in card["fields"]
            ]
            presence = _presence_spec(card, fields)
            spec = {
                "uid": card["uid"],
                "name": card.get("name", ""),
                "fields": fields,
                "presence": presence,
            }
            if wire.get("id") is not None:
                emitted.append(card["uid"])
                messages.append(
                    {
                        **spec,
                        "wire_id": int(str(wire["id"]), 0),
                        "direction": wire.get("direction", ""),
                    }
                )
            else:
                # A ready card with no wire id is a named nested sub-codec, not a
                # message: it is emitted into CODECS, never into MESSAGES.
                codecs.append(spec)
        elif status == "refused":
            refused.append((card["uid"], "; ".join(reasons)))
        else:
            fieldless.append(card["uid"])

    messages.sort(key=lambda spec: (spec["wire_id"], spec["uid"]))
    codecs.sort(key=lambda spec: spec["uid"])

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = {
        "wire.py": render_wire_py(*vocabulary, messages, codecs),
        "wire.rs": render_wire_rs(*vocabulary, messages, codecs),
        "meanings-table.md": render_meanings_md(classifications),
    }
    for name, text in rendered.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")

    # The emitted Rust must be rustfmt-clean so `cargo fmt --check` passes on the
    # crate; running the project's own formatter here keeps the generator output
    # and the crate identical. python and rustfmt are the only writers here.
    wire_rs_path = out_dir / "wire.rs"
    rustfmt(wire_rs_path)
    rendered["wire.rs"] = wire_rs_path.read_text(encoding="utf-8")

    crate_artifact = None
    if crate_out is not None:
        crate_out = Path(crate_out)
        crate_out.parent.mkdir(parents=True, exist_ok=True)
        crate_out.write_text(rendered["wire.rs"], encoding="utf-8", newline="\n")
        crate_artifact = str(crate_out)

    return {
        "emitted": emitted,
        "codecs": codecs,
        "refused": refused,
        "fieldless": fieldless,
        "artifacts": [str(out_dir / name) for name in ARTIFACTS],
        "crate_artifact": crate_artifact,
    }


def _relative(path: str) -> str:
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return path


def rustfmt(path: Path) -> None:
    """Format one emitted Rust file in place with the project's rustfmt."""
    try:
        subprocess.run(
            ["rustfmt", "--edition", CRATE_EDITION, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "rustfmt is required to emit the Rust codec; install it with the toolchain"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"rustfmt failed on {path}: {exc.stderr}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate wire code and a meanings table from the Atlas cards."
    )
    parser.add_argument("--schema", default=str(SCHEMA))
    parser.add_argument("--concepts", default=str(CONCEPTS))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--crate-out", default=str(WIRE_RS_CRATE))
    args = parser.parse_args(argv)

    report = generate(
        Path(args.schema), Path(args.concepts), Path(args.out), Path(args.crate_out)
    )
    total = (
        len(report["emitted"])
        + len(report["codecs"])
        + len(report["refused"])
        + len(report["fieldless"])
    )
    print(f"ontology-gen: {total} cards")
    print(f"emitted (message wire code): {len(report['emitted'])}")
    for uid in report["emitted"]:
        print(f"  - {uid}")
    print(f"emitted (nested sub-codecs): {len(report['codecs'])}")
    for spec in report["codecs"]:
        print(f"  - {spec['uid']}")
    print(f"refused (markdown only): {len(report['refused'])}")
    for uid, reason in report["refused"]:
        print(f"  - {uid}: {reason}")
    print(f"field-less (neither emitted nor refused): {len(report['fieldless'])}")
    for uid in report["fieldless"]:
        print(f"  - {uid}")
    for path in report["artifacts"]:
        print(f"wrote {_relative(path)}")
    if report["crate_artifact"]:
        print(f"wrote {_relative(report['crate_artifact'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
