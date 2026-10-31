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
    """FIX 1 and FIX 2 rules plus the literal-count rule; run for every card,
    legacy included."""
    return (
        prefixed_length_errors(concept)
        + envelope_errors(concept)
        + literal_count_errors(concept)
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


def classify(concept: dict, schema: dict) -> tuple[str, str]:
    """Return (kind, detail) for one card; kind is ok | legacy | fail."""
    modelling = modelling_errors(concept)
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
    for path in files:
        try:
            concept = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            lines.append(f"FAIL {path.stem}  {exc}")
            failed = True
            continue
        has_fields = bool(_fields(concept))
        if has_fields:
            fielded += 1
        else:
            fieldless += 1
        kind, detail = classify(concept, schema)
        if kind == "legacy":
            lines.append(f"LEGACY {path.stem} ({detail})")
        elif kind == "fail":
            lines.append(f"FAIL {path.stem}  {detail}")
            failed = True
        else:
            lines.append(f"OK {path.stem}  {detail}")
            if has_fields and detail == "ready":
                ready += 1
        opaque_total += opaque_count(concept)
    lines.append(
        f"summary: {len(files)} cards (fielded {fielded}, field-less {fieldless}); "
        f"fielded codegen-ready: {ready}/{fielded}; {opaque_total} opaque fields"
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
