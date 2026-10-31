# Protocol / platform ontology

Scalable fact store for agents. One concept = one JSON file under `concepts/`.
Indexes under `indexes/` are generated or hand-maintained stubs until
`ef.py atlas index` exists.

## Confidence ladder

| Level | Meaning | May drive production sim? |
| --- | --- | --- |
| `bytes` | Client accepts or sends these bytes | Fixtures / ladders only |
| `layout` | Field offsets/types measured | Codecs in `azoth-wire` |
| `semantics` | Know what state changes / why | Handlers allowed |
| `authoritative` | Server originates the value | Sole production path |

## Status values

`unknown` → `candidate` → `verified` → `implemented` → `retired`

LLM output stops at `candidate`. Promotion needs a second signal (see schema).

## Layout

```text
schema.json           # JSON Schema for concept files
glossary.md           # stable vocabulary
competency-questions.md
concepts/*.json       # msg.*, sys.*, flow.*, cmd.*, …
indexes/              # by-uid, by-wire, by-kind (stubs OK)
```

## Rules

- Link from docs; do not copy full concept bodies into STATUS or ROADMAP.
- Binary-dependent facts carry full executable SHA-256 in `build`.
- Raw captures stay in ignored `research/sessions/`.
- `schema.json` sets `additionalProperties: false`, so a key it does not declare is
  a defect even though the file is still valid JSON. Run
  `python scripts/check/check-atlas.py`; it enforces the schema's `required` list
  and its `properties` allowlist over every concept file, and CI runs it with the
  other gates. It reads the rules from the schema, so widening the schema widens
  the check.
- The codec vocabulary in `$defs.codec` is closed. `prefixed_bytes` and
  `prefixed_string` INCLUDE their length prefix — the prefix varint is part of the
  codec — so a standalone `prefix_varint` field immediately before one of them
  double-counts the length. The validator FAILs that shape.
- `fields[]` describes the message BODY only. The record envelope
  (`[vlq32 length][00 01][prefix-varint type]`) is generic framing owned by
  `services/world/src/azoth_world/javelin/frame.py` (and `bundle.py`) and is never
  a `fields[]` item; record it in the card-level `envelope` string instead. The
  validator FAILs a `fields[]` item whose name or note is an envelope name
  (`record_header`, `typed_header`, `type_prefix`, `vlq`), or a `00 01` note
  beside a type/prefix mention.
- Each `fields` item is closed by `$defs.field`/`$defs.codec` in `schema.json`:
  `name`, `type` and `evidence` are required, `type` must be a frozen codec
  vocabulary member (or `opaque(id)`), and any other key is a defect. Run
  `python reverse/tools/atlas/ontology-validate.py`; it prints one line per card
  (`OK … ready`, `OK … not-ready (n opaque)`, `OK … field-less`, `LEGACY …`,
  `FAIL …`) then a summary
  (`summary: N cards (fielded F, field-less L); fielded codegen-ready: R/F; M opaque fields`)
  and exits 1 on any FAIL. A field-less card is neither ready nor not-ready, so it
  never counts toward the codegen-ready number. `legacy: true` cards skip field
  validation, but the prefixed-length and envelope rules still run on them.
- Three compositional codecs carry records that are not a flat field list:
  `nested(<uid>)` is another codec card's body (the named card must exist, be a
  `codec`, model fields, and not be `unknown`), `counted(<element>)` is a
  prefix-varint count followed by elements whose element codec has a layout of its
  own, and `optional(<codec>)` is a STRICT zero-or-one flag byte followed by the
  value only when the flag is 1 (a flag above 1 is refused, never read as true).
  Each carries its own `$comment` in `$defs.codec`, and `opaque(id)` stays the
  honest escape when none of them fits.
- Conditional membership is a CARD-LEVEL `presence` block plus coordinates on each
  field. A card with `presence` has no flat field order: its body is `[group mask
  byte][for each present group: member mask byte][the present members in ascending
  order]`, and a field is on the wire only when both its group bit and its member
  bit are set. Declare each member with `"presence": {"group": g, "member": m}`.
  One mask byte per level is modelled (`bits` usable low-first bits, optional
  `continuation` bit meaning a further byte), so the validator rejects an index
  that does not fit its level, two members sharing coordinates, a card that
  declares `presence` yet leaves a wire field without coordinates, and a card that
  puts coordinates on a field with no `presence` block. A body whose mask sets a
  bit for an undeclared group or member is REFUSED by the codec, never skipped.
- Put a decoded struct's members in `fields` with `"where": "memory"`, not in an
  ad-hoc top-level key. MEASURED 2026-10-25: before the checker existed a `struct`
  block and an `open_questions` list had both been introduced as top-level keys.
  A `memory` field carries a decoded-struct offset and can never drive codegen,
  but still declares a `type`.
