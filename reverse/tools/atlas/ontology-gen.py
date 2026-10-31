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
  - `wire.rs`            the same structure as a Rust PREVIEW. It is marked at
                         the top as a non-compiling preview and no crate is made.
  - `meanings-table.md`  the human-readable rendering: one section per card, one
                         row per field (name, type, offset, evidence, note).

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY = ROOT / "research" / "atlas" / "ontology"
SCHEMA = ONTOLOGY / "schema.json"
CONCEPTS = ONTOLOGY / "concepts"
OUT = ROOT / "research" / "generated"

ARTIFACTS = ("wire.py", "wire.rs", "meanings-table.md")

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
) -> tuple[str, list[str]]:
    """Return (status, reasons) where status is ready | refused | field-less."""
    fields = card.get("fields") or []
    if not fields:
        return "field-less", []

    members, patterns = vocabulary if vocabulary else _default_vocabulary()
    opaque: list[str] = []
    memory: list[str] = []
    unknown_evidence: list[str] = []
    off_vocabulary: list[str] = []
    reasons: list[str] = []
    if card.get("status") == "unknown":
        reasons.append("card status is 'unknown'")
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
'''


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
        for name, type_name in spec["fields"]:
            lines.append(f"            ({name!r}, {type_name!r}),")
        lines.append("        ),")
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("# --- card-derived nested sub-codecs (not messages) ---")
    lines.append("CODECS = {")
    for spec in codecs:
        lines.append(f"    {spec['uid']!r}: {{")
        lines.append(f"        'name': {spec['name']!r},")
        lines.append("        'fields': (")
        for name, type_name in spec["fields"]:
            lines.append(f"            ({name!r}, {type_name!r}),")
        lines.append("        ),")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


# --- generated Rust preview ---------------------------------------------------

_WIRE_RS_HEADER = '''\
// NON-COMPILING PREVIEW -- generated from the Atlas concept cards by
// `reverse/tools/atlas/ontology-gen.py`. This file is NOT a crate and is NOT
// meant to build; it previews the same table-driven layout as wire.py so the
// Rust port can be reviewed field by field. Do not `mod` it into anything.
//
// Envelope note: every field is a message BODY field. The `00 01` + prefix-varint
// type record envelope is framing owned by javelin/frame.py, never a field here.
//
// The measured prefix-varint primitive is `azoth_world.javelin.varint`; this
// preview mirrors wire.py and does not reimplement it.
'''


def render_wire_rs(
    members: list[str], patterns: list[str], messages: list[dict], codecs: list[dict]
) -> str:
    lines = [_WIRE_RS_HEADER, "", "pub const VOCABULARY: &[&str] = &["]
    for member in members:
        lines.append(f'    "{member}",')
    lines.append("];")
    lines.append("")
    lines.append("pub struct FieldSpec {")
    lines.append("    pub name: &'static str,")
    lines.append("    pub codec: &'static str,")
    lines.append("}")
    lines.append("")
    lines.append("pub struct MessageSpec {")
    lines.append("    pub wire_id: u32,")
    lines.append("    pub uid: &'static str,")
    lines.append("    pub name: &'static str,")
    lines.append("    pub direction: &'static str,")
    lines.append("    pub fields: &'static [FieldSpec],")
    lines.append("}")
    lines.append("")
    lines.append("pub static MESSAGES: &[MessageSpec] = &[")
    for spec in messages:
        lines.append("    MessageSpec {")
        lines.append(f"        wire_id: {spec['wire_id']},")
        lines.append(f'        uid: "{spec["uid"]}",')
        lines.append(f'        name: "{spec["name"]}",')
        lines.append(f'        direction: "{spec["direction"]}",')
        lines.append("        fields: &[")
        for name, type_name in spec["fields"]:
            lines.append(f'            FieldSpec {{ name: "{name}", codec: "{type_name}" }},')
        lines.append("        ],")
        lines.append("    },")
    lines.append("];")
    lines.append("")
    lines.append("pub struct CodecSpec {")
    lines.append("    pub uid: &'static str,")
    lines.append("    pub name: &'static str,")
    lines.append("    pub fields: &'static [FieldSpec],")
    lines.append("}")
    lines.append("")
    lines.append("pub static CODECS: &[CodecSpec] = &[")
    for spec in codecs:
        lines.append("    CodecSpec {")
        lines.append(f'        uid: "{spec["uid"]}",')
        lines.append(f'        name: "{spec["name"]}",')
        lines.append("        fields: &[")
        for name, type_name in spec["fields"]:
            lines.append(f'            FieldSpec {{ name: "{name}", codec: "{type_name}" }},')
        lines.append("        ],")
        lines.append("    },")
    lines.append("];")
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
        if status == "ready":
            lines.append("- codegen: **ready** — wire code emitted")
        elif status == "refused":
            lines.append("- codegen: **refused** — " + "; ".join(reasons))
        else:
            lines.append("- codegen: field-less — neither emitted nor refused")
        lines.append("")
        fields = card.get("fields") or []
        if fields:
            lines.append("| field | type | offset | evidence | note |")
            lines.append("| --- | --- | --- | --- | --- |")
            for field in fields:
                lines.append(
                    "| {name} | {type} | {offset} | {evidence} | {note} |".format(
                        name=_cell(field.get("name")),
                        type=_cell(field.get("type")),
                        offset=_cell(field.get("offset", "—")),
                        evidence=_cell(field.get("evidence")),
                        note=_cell(field.get("note", "")),
                    )
                )
            lines.append("")
    return "\n".join(lines) + "\n"


# --- driver -------------------------------------------------------------------


def generate(schema_path, concepts_dir, out_dir) -> dict:
    """Emit the three artifacts into ``out_dir``; return the gate report."""
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    vocabulary = load_vocabulary(schema)

    classifications: list[tuple[dict, str, list[str]]] = []
    for path in sorted(Path(concepts_dir).glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        status, reasons = classify(card, vocabulary)
        classifications.append((card, status, reasons))

    emitted: list[str] = []
    refused: list[tuple[str, str]] = []
    fieldless: list[str] = []
    messages: list[dict] = []
    codecs: list[dict] = []
    for card, status, reasons in classifications:
        if status == "ready":
            wire = card.get("wire") or {}
            fields = [(f["name"], _field_codec(f)) for f in card["fields"]]
            if wire.get("id") is not None:
                emitted.append(card["uid"])
                messages.append(
                    {
                        "wire_id": int(str(wire["id"]), 0),
                        "uid": card["uid"],
                        "name": card.get("name", ""),
                        "direction": wire.get("direction", ""),
                        "fields": fields,
                    }
                )
            else:
                # A ready card with no wire id is a named nested sub-codec, not a
                # message: it is emitted into CODECS, never into MESSAGES.
                codecs.append(
                    {
                        "uid": card["uid"],
                        "name": card.get("name", ""),
                        "fields": fields,
                    }
                )
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

    return {
        "emitted": emitted,
        "codecs": codecs,
        "refused": refused,
        "fieldless": fieldless,
        "artifacts": [str(out_dir / name) for name in ARTIFACTS],
    }


def _relative(path: str) -> str:
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate wire code and a meanings table from the Atlas cards."
    )
    parser.add_argument("--schema", default=str(SCHEMA))
    parser.add_argument("--concepts", default=str(CONCEPTS))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    report = generate(Path(args.schema), Path(args.concepts), Path(args.out))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
