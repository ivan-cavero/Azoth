#!/usr/bin/env python3
"""Validate every atlas ontology concept field against the closed field schema.

WHY THIS EXISTS
===============
`research/atlas/ontology/schema.json` used to declare its `fields` items as a
bare `{"type": "object"}`, so every card validated and nothing constrained the
codec a field claims. MEASURED 2026-10-25: that hole is why `scripts/check/
check-atlas.py` could only check card-level keys. The `$defs.field` /
`$defs.codec` blocks now close it, and this validator is the thing that reads
them back.

`scripts/check/check-atlas.py` deliberately implements only `required` and the
`properties` allowlist and says deeper validation "would need a dependency the
lab does not pin". This validator is standard-library only and walks the schema
itself, so it adds no dependency: it interprets the exact JSON Schema keywords
the field schema uses (`$ref`, `oneOf`, `enum`, `pattern`, `type`, `required`,
`properties`, `additionalProperties`, `minLength`, `items`). The vocabulary
therefore lives once, in the schema.

OUTCOMES (one line per card)
============================
- `OK <card>  ready`               every field is a wire codec that is not
                                   `opaque(...)` and the card is not `unknown`
- `OK <card>  not-ready (n opaque)` a valid card with n `opaque(...)` fields
- `OK <card>  field-less`          a valid card with no `fields[]` at all: it is
                                   neither ready nor not-ready, so it must not
                                   inflate the codegen-ready count
- `LEGACY <card> (n fields unvalidated)`  the card set `legacy: true`, so its
                                   field items are skipped, never failed
- `FAIL <card>  <reason>`          a card that double-counts a length prefix, puts
                                   the record envelope in `fields[]`, or otherwise
                                   does not conform

Exit code is 1 if any card FAILs, else 0. A summary line follows with the
fielded/field-less split, the ready count among fielded cards only, and the
total opaque field count.

TWO MODELLING RULES BEYOND THE CLOSED FIELD SCHEMA (PLUS THE LITERAL-COUNT RULE)
==================================================================================
`prefixed_bytes`/`prefixed_string` INCLUDE their length prefix, so a field that
is one of them immediately after a `prefix_varint` field double-counts the
prefix (codegen would emit it twice). `fields[]` is also the message BODY only:
the `[00 01 <prefix-varint type>]` record envelope is owned by
`services/world/src/azoth_world/javelin/frame.py` and must never be a field.
A JSON integer `count` is a LITERAL element count and is only meaningful on a
`vec<T>`/`matrix<T>`. All rules run before the `legacy` skip, so a legacy card
can still FAIL.

THE MEANING RULE (VISIBILITY, NEVER A GATE)
===========================================
Every field declares `meaning`: `known` (we know what it carries) or
`layout-only` (we know the bytes, not the meaning). A field with no `meaning`
FAILs. A placeholder name -- `field_*`, `unresolved_*`, `unknown_*`, `raw*`,
`blob*`, `head`, `*_at_0x*`, a name that is only a type or an offset -- MUST be
`layout-only` and may never claim `known`. A field claiming `known` must carry a
`note` that actually says what it is. This marking never makes a card
un-codegen-ready: the layout is known, so the codec is correct.

The summary reports, per card and in total, how many fields are `known` and how
many are `layout-only`.

Usage:
    python reverse/tools/atlas/ontology-validate.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY = ROOT / "research" / "atlas" / "ontology"
SCHEMA = ONTOLOGY / "schema.json"
CONCEPTS = ONTOLOGY / "concepts"


def _resolve(schema: dict, ref: str) -> dict:
    node: dict = schema
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _is_type(value: object, name: str) -> bool:
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "null":
        return value is None
    return True


def _matches(value: object, alt: dict, schema: dict) -> bool:
    """oneOf alternatives in this schema are plain enum/pattern members."""
    if "$ref" in alt:
        alt = _resolve(schema, alt["$ref"])
    if "enum" in alt:
        return value in alt["enum"]
    if "pattern" in alt:
        return isinstance(value, str) and re.search(alt["pattern"], value) is not None
    return False


def _check(node: dict, value: object, schema: dict, path: str, errors: list[str]) -> None:
    if "$ref" in node:
        _check(_resolve(schema, node["$ref"]), value, schema, path, errors)
        return
    if "oneOf" in node:
        if not any(_matches(value, alt, schema) for alt in node["oneOf"]):
            errors.append(f"{path}: {value!r} is not a codec vocabulary member")
        return
    declared = node.get("type")
    if declared is not None:
        allowed = declared if isinstance(declared, list) else [declared]
        if not any(_is_type(value, name) for name in allowed):
            errors.append(f"{path}: expected {declared}, got {type(value).__name__}")
            return
    if isinstance(value, dict) and "properties" in node:
        props = node["properties"]
        for key in node.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        for key, member in value.items():
            if key in props:
                _check(props[key], member, schema, f"{path}.{key}", errors)
            elif node.get("additionalProperties") is False:
                errors.append(f"{path}: key {key!r} is not allowed by schema.json")
    if isinstance(value, str):
        if "enum" in node and value not in node["enum"]:
            errors.append(f"{path}: {value!r} not one of {node['enum']}")
        if "pattern" in node and re.search(node["pattern"], value) is None:
            errors.append(f"{path}: {value!r} does not match {node['pattern']}")
        if "minLength" in node and len(value) < node["minLength"]:
            errors.append(f"{path}: {value!r} is shorter than {node['minLength']}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{path}: {value} is below the minimum {node['minimum']}")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{path}: {value} is above the maximum {node['maximum']}")
    if isinstance(value, list) and "items" in node:
        for i, member in enumerate(value):
            _check(node["items"], member, schema, f"{path}[{i}]", errors)


def validate_concept(concept: object, schema: dict) -> list[str]:
    """Every schema violation in one card; empty means it conforms."""
    errors: list[str] = []
    _check(schema, concept, schema, "concept", errors)
    return errors


def _fields(concept: dict) -> list:
    fields = concept.get("fields")
    return fields if isinstance(fields, list) else []


def opaque_count(concept: dict) -> int:
    return sum(
        1 for f in _fields(concept) if str(f.get("type", "")).startswith("opaque(")
    )


# The two honest states of a field's meaning. `layout-only` is a true statement
# about our knowledge, not a defect: we know the bytes, not what they carry.
MEANING_VALUES = frozenset({"known", "layout-only"})

# A placeholder name tells us nothing about what the field carries, so it can
# never claim `known`. `raw*`/`blob*` are here because a raw run states no
# meaning; the other shapes are the card conventions for "we only know the
# layout". A name that is only a codec token (optionally indexed) or an offset
# is a placeholder too.
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^field_"),
    re.compile(r"^unresolved_"),
    re.compile(r"^unknown_"),
    re.compile(r"^raw"),
    re.compile(r"^blob"),
    re.compile(r"^head"),
    re.compile(r"_at_0x"),
    re.compile(r"_from_0x"),
    re.compile(r"0x"),
    re.compile(
        r"^(?:u8|u16|u32|u64|i8|i16|i32|i64|f32|f64|enum\d*|bitset\d*|bool(?:_byte)?)"
        r"(?:_?(?:be|le))?(?:_\d+)?$"
    ),
    re.compile(r"^(?:first|second|third|fourth)$"),
    re.compile(r"^trailing_bool(?:_\d+)?$"),
)


def _is_placeholder_name(name: object) -> bool:
    """True when a field name says nothing about what the field carries."""
    if not isinstance(name, str):
        return False
    return any(pattern.search(name) for pattern in _PLACEHOLDER_PATTERNS)


def _meaning_census(concept: dict) -> tuple[int, int]:
    """(known, layout-only) field counts for one card."""
    known = sum(1 for f in _fields(concept) if f.get("meaning") == "known")
    layout_only = sum(
        1 for f in _fields(concept) if f.get("meaning") == "layout-only"
    )
    return known, layout_only


def meaning_errors(concept: dict) -> list[str]:
    """The meaning rule: presence, placeholder honesty, and a real note.

    Runs for every card, `legacy` included, because the rule is about what we
    claim to know, not about whether the closed field schema applies.
    """
    errors: list[str] = []
    for field in _fields(concept):
        name = field.get("name")
        if "meaning" not in field:
            errors.append(f"field {name!r} does not declare a meaning")
            continue
        meaning = field.get("meaning")
        if meaning not in MEANING_VALUES:
            errors.append(
                f"field {name!r} meaning {meaning!r} is not one of "
                f"{sorted(MEANING_VALUES)}"
            )
            continue
        if _is_placeholder_name(name) and meaning != "layout-only":
            errors.append(
                f"field {name!r} is a placeholder name and must be layout-only, "
                f"not {meaning!r}"
            )
        if meaning == "known":
            note = field.get("note")
            if not isinstance(note, str) or not note.strip():
                errors.append(
                    f"field {name!r} claims meaning known but has no note saying "
                    f"what it is"
                )
    return errors


# FIX 1: the length lives inside these codecs; a separate prefix_varint before one
# of them double-counts it and would make a code generator emit the prefix twice.
PREFIXED_TYPES = frozenset({"prefixed_bytes", "prefixed_string"})

# FIX 2: these names/notes describe the record envelope, which frame.py owns.
ENVELOPE_TOKEN = re.compile(r"record_header|typed_header|type_prefix|\bvlq\b")
ENVELOPE_MARKER = "00 01"
ENVELOPE_TYPE_WORD = re.compile(r"type|prefix", re.IGNORECASE)


def prefixed_length_errors(concept: dict) -> list[str]:
    """FIX 1: a prefixed_* field immediately after a prefix_varint field."""
    errors: list[str] = []
    fields = _fields(concept)
    for prev, cur in zip(fields, fields[1:]):
        if (
            cur.get("type") in PREFIXED_TYPES
            and prev.get("type") == "prefix_varint"
        ):
            errors.append(
                f"field {cur.get('name')!r} is {cur.get('type')} immediately after "
                f"prefix_varint {prev.get('name')!r}; the length is already inside "
                f"the codec"
            )
    return errors


def envelope_errors(concept: dict) -> list[str]:
    """FIX 2: a fields[] item that models the record envelope."""
    errors: list[str] = []
    for field in _fields(concept):
        name = str(field.get("name", ""))
        note = str(field.get("note", ""))
        if ENVELOPE_TOKEN.search(name) or ENVELOPE_TOKEN.search(note):
            errors.append(
                f"field {name!r} models the record envelope; the envelope is "
                f"framing owned by javelin/frame.py, not a fields[] item"
            )
        elif ENVELOPE_MARKER in note and ENVELOPE_TYPE_WORD.search(note):
            errors.append(
                f"field {name!r} note models the record envelope "
                f"({ENVELOPE_MARKER!r} beside a type/prefix mention)"
            )
    return errors


def modelling_errors(concept: dict) -> list[str]:
    """FIX 1 and FIX 2 rules, the literal-count rule, the presence rule and the
    meaning rule; run for every card, legacy included."""
    return (
        prefixed_length_errors(concept)
        + envelope_errors(concept)
        + literal_count_errors(concept)
        + presence_errors(concept)
        + meaning_errors(concept)
    )


# FIX 3: `count` may be the string "prefix_varint" (a dynamic count) or a JSON
# integer (a LITERAL element count). The integer form is only meaningful on a
# composite that carries its elements directly, so it must be on vec<T>/matrix<T>
# and must be at least 1.
COMPOSITE_TYPE = re.compile(r"^(?:vec|matrix)<.+>$")


def literal_count_errors(concept: dict) -> list[str]:
    """FIX 3: an integer `count` must be a positive literal on a composite."""
    errors: list[str] = []
    for field in _fields(concept):
        count = field.get("count")
        if isinstance(count, bool) or not isinstance(count, int):
            continue
        name = field.get("name")
        type_name = str(field.get("type", ""))
        if not COMPOSITE_TYPE.match(type_name):
            errors.append(
                f"field {name!r} has the literal count {count} but type "
                f"{type_name!r} is not vec<T>/matrix<T>"
            )
        elif count < 1:
            errors.append(
                f"field {name!r} has a literal count of {count}; it must be at least 1"
            )
    return errors


# A nested(<uid>) reference inside any codec string, including counted(...)/optional(...).
NESTED_REF = re.compile(r"nested\(([^()]*)\)")


def nested_references(concept: dict) -> list[str]:
    """Every codec card this card's field types name as a nested record."""
    refs: list[str] = []
    for field in _fields(concept):
        refs.extend(
            match.group(1) for match in NESTED_REF.finditer(str(field.get("type", "")))
        )
    return refs


def presence_errors(concept: dict) -> list[str]:
    """The two-level presence mask's semantics, which the schema cannot state.

    A card either declares `presence` and puts coordinates on every wire field,
    or declares none and puts coordinates on no field. A level WITHOUT a
    `continuation` is ONE mask byte, so an index has to fit its `bits`. A level
    WITH one is a continuation sequence: the reader keeps reading mask bytes
    while the continuation bit (the single bit above the member bits) is set, so
    an index wider than `bits` is legal and lands in a later byte. A level WITH
    `varint` is one wide prefix varint whose integer value is the bitmask, so an
    index wider than `bits` is legal there too. Two fields still cannot share a
    coordinate.
    """
    errors: list[str] = []
    declared = concept.get("presence")
    fields = _fields(concept)
    if not isinstance(declared, dict):
        for field in fields:
            if "presence" in field:
                errors.append(
                    f"field {field.get('name')!r} declares presence coordinates but "
                    f"the card declares no two-level `presence` mask"
                )
        return errors

    bounds: dict[str, int] = {}
    names: dict[str, object] = {}
    sequences: dict[str, bool] = {}
    for level in ("group", "member"):
        node = declared.get(level)
        if not isinstance(node, dict):
            errors.append(f"presence level {level!r} is missing")
            continue
        names[level] = node.get("name")
        bits = node.get("bits")
        if isinstance(bits, bool) or not isinstance(bits, int) or not 1 <= bits <= 8:
            errors.append(f"presence level {level!r} bits must be an integer 1..8")
            continue
        bounds[level] = bits
        continuation = node.get("continuation")
        varint = bool(node.get("varint", False))
        if continuation is not None and varint:
            errors.append(
                f"presence level {level!r} cannot be both a continuation sequence "
                f"and a prefix-varint bitmask"
            )
        sequences[level] = continuation is not None or varint
        if continuation is None:
            continue
        if isinstance(continuation, bool) or not isinstance(continuation, int):
            errors.append(
                f"presence level {level!r} continuation must be the continuation bit's value"
            )
        elif bits >= 8:
            errors.append(
                f"presence level {level!r} uses all 8 bits, so no bit is left for a "
                f"continuation"
            )
        elif continuation != 1 << bits:
            errors.append(
                f"presence level {level!r} continuation {continuation} is not the bit "
                f"above its {bits} member bits ({1 << bits})"
            )
    if names.get("group") is not None and names.get("group") == names.get("member"):
        errors.append("the two presence levels cannot share one mask field name")
    if not fields:
        errors.append("a card declaring `presence` models no members")

    seen: dict[tuple[object, object], object] = {}
    for field in fields:
        name = field.get("name")
        if field.get("where", "wire") != "wire":
            errors.append(
                f"field {name!r} is a memory field, so it cannot carry wire presence "
                f"coordinates"
            )
            continue
        coords = field.get("presence")
        if not isinstance(coords, dict):
            errors.append(
                f"field {name!r} has no presence coordinates; every wire field of a "
                f"masked card needs presence:{{group,member}}"
            )
            continue
        group = coords.get("group")
        member = coords.get("member")
        if isinstance(group, bool) or not isinstance(group, int) or group < 0:
            errors.append(f"field {name!r} presence group must be a non-negative integer")
            continue
        if isinstance(member, bool) or not isinstance(member, int) or member < 0:
            errors.append(
                f"field {name!r} presence member must be a non-negative integer"
            )
            continue
        if "group" in bounds and not sequences.get("group") and group >= bounds["group"]:
            errors.append(
                f"field {name!r} names group {group}, which does not fit the "
                f"{bounds['group']}-bit group mask"
            )
        if (
            "member" in bounds
            and not sequences.get("member")
            and member >= bounds["member"]
        ):
            errors.append(
                f"field {name!r} names member {member}, which does not fit the "
                f"{bounds['member']}-bit member mask"
            )
        if (group, member) in seen:
            errors.append(
                f"field {name!r} repeats the duplicate presence coordinates group "
                f"{group} member {member} of field {seen[(group, member)]!r}"
            )
        else:
            seen[(group, member)] = name
    return errors


def reference_errors(concept: dict, cards_by_uid: dict[str, dict]) -> list[str]:
    """Every nested(<uid>) must name a real, usable codec card."""
    errors: list[str] = []
    for uid in nested_references(concept):
        target = cards_by_uid.get(uid)
        if target is None:
            errors.append(f"nested record names no card: {uid}")
        elif target.get("kind") != "codec":
            errors.append(
                f"nested record {uid} is a {target.get('kind')} card, not a codec card"
            )
        elif not _fields(target):
            errors.append(f"nested record {uid} models no fields")
        elif target.get("status") == "unknown":
            errors.append(f"nested record {uid} has status unknown")
    return errors


def card_is_ready(concept: dict) -> bool:
    """Codegen-ready per the schema's `$defs.field` $comment: no opaque codec,
    no memory field, the card itself is not `unknown`, and it actually models at
    least one field. An empty/absent `fields[]` is neither ready nor not-ready."""
    if not _fields(concept):
        return False
    if concept.get("status") == "unknown":
        return False
    for field in _fields(concept):
        if field.get("where", "wire") != "wire":
            return False
        if str(field.get("type", "")).startswith("opaque("):
            return False
    return True


def classify(
    concept: dict, schema: dict, cards_by_uid: dict[str, dict] | None = None
) -> tuple[str, str]:
    """Return (kind, detail) for one card; kind is ok | legacy | fail.

    ``cards_by_uid`` is the whole concept set when the caller has it: nested
    record references can only be checked against every card, so a per-card call
    without it skips that one rule.
    """
    modelling = modelling_errors(concept)
    if cards_by_uid is not None:
        modelling = modelling + reference_errors(concept, cards_by_uid)
    if modelling:
        return "fail", "; ".join(modelling)
    if concept.get("legacy") is True:
        return "legacy", f"{len(_fields(concept))} fields unvalidated"
    if not _fields(concept):
        return "ok", "field-less"
    errors = validate_concept(concept, schema)
    if errors:
        return "fail", "; ".join(errors)
    if card_is_ready(concept):
        return "ok", "ready"
    return "ok", f"not-ready ({opaque_count(concept)} opaque)"


def validate_dir(schema_path: Path, concepts_dir: Path) -> tuple[list[str], int]:
    """One line per card in `concepts_dir`, then a summary. Exit code 1 on FAIL."""
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    files = sorted(Path(concepts_dir).glob("*.json"))
    lines: list[str] = []
    failed = False
    fielded = 0
    fieldless = 0
    ready = 0
    opaque_total = 0
    known_total = 0
    layout_only_total = 0
    # Every card first: a nested(<uid>) reference can only be checked against the
    # whole set, so the cards are loaded before any one of them is classified.
    cards: list[tuple[Path, object]] = []
    cards_by_uid: dict[str, dict] = {}
    for path in files:
        try:
            concept = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            cards.append((path, exc))
            continue
        cards.append((path, concept))
        uid = concept.get("uid") if isinstance(concept, dict) else None
        if isinstance(uid, str):
            cards_by_uid[uid] = concept
    for path, loaded in cards:
        if not isinstance(loaded, dict):
            lines.append(f"FAIL {path.stem}  {loaded}")
            failed = True
            continue
        concept = loaded
        has_fields = bool(_fields(concept))
        if has_fields:
            fielded += 1
        else:
            fieldless += 1
        known, layout_only = _meaning_census(concept)
        known_total += known
        layout_only_total += layout_only
        census = f"[meaning: {known} known, {layout_only} layout-only]"
        kind, detail = classify(concept, schema, cards_by_uid)
        if kind == "legacy":
            lines.append(f"LEGACY {path.stem} ({detail})  {census}")
        elif kind == "fail":
            lines.append(f"FAIL {path.stem}  {detail}")
            failed = True
        else:
            lines.append(f"OK {path.stem}  {detail}  {census}")
            if has_fields and detail == "ready":
                ready += 1
        opaque_total += opaque_count(concept)
    lines.append(
        f"summary: {len(files)} cards (fielded {fielded}, field-less {fieldless}); "
        f"fielded codegen-ready: {ready}/{fielded}; {opaque_total} opaque fields; "
        f"fields: {known_total} known, {layout_only_total} layout-only"
    )
    return lines, (1 if failed else 0)


def main() -> int:
    if not SCHEMA.is_file():
        print("ontology-validate: schema.json is missing", file=sys.stderr)
        return 1
    if not CONCEPTS.is_dir():
        print("ontology-validate: concepts/ is missing", file=sys.stderr)
        return 1
    lines, code = validate_dir(SCHEMA, CONCEPTS)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
