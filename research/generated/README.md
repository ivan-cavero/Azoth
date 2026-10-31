# research/generated

Artifacts generated from `research/atlas/ontology/schema.json` and the Atlas
concept cards. Do not edit by hand: everything here is overwritten by the
generator.

Single command:

```text
python ef.py re ontology-gen
```

That is registered in `reverse/tools/catalog.json` as the `ontology-gen`
workflow, so the direct invocation `python reverse/tools/atlas/ontology-gen.py`
is only a fallback.

## Outputs

| file | what it is |
| --- | --- |
| `wire.py` | Table-driven encoder/decoder for the closed codec vocabulary. Per-message layouts are derived from the cards; the measured prefix-varint primitive is imported from `services/world/src/azoth_world/javelin/varint.py`. |
| `wire.rs` | The same structure as a Rust preview. It is marked non-compiling at the top; no crate is created. |
| `meanings-table.md` | One section per card, one row per field (name, type, offset, evidence, note). The generated replacement for the prose tables in `meanings.md`. |

The generator refuses wire code for any card that is not codegen-ready (an
`opaque(...)` field, a `where: memory` field, an unknown field evidence, an
unknown card status, or a type outside the closed vocabulary) while still
emitting its markdown. A card with no `fields[]` is reported as field-less.

Output is deterministic: two consecutive runs produce byte-identical artifacts.
