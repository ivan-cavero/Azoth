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
| `wire.rs` | The compiling Rust codec: one typed struct per codegen-ready card, with `decode`/`encode`. The generator writes the exact same text into `server/crates/everfall-wire/src/generated/mod.rs`, so the reviewed artifact and the crate cannot drift. Formatted in place with the project's `rustfmt`. |
| `meanings-table.md` | One section per card, one row per field (name, type, offset, evidence, note). The generated replacement for the prose tables in `meanings.md`. |

The generator refuses wire code for any card that is not codegen-ready (an
`opaque(...)` field, a `where: memory` field, an unknown field evidence, an
unknown card status, or a type outside the closed vocabulary) while still
emitting its markdown. A card with no `fields[]` is reported as field-less.

A raw byte run (`bytes(n)`, `prefixed_bytes`, `guid16`) is emitted as an
`Opaque` newtype that carries its Atlas id, never a bare `Vec<u8>`; the crate
therefore cannot shuttle an unnamed field. The library also never reads a file:
a fixture is evidence for a test, not an input to the codec.

Output is deterministic: two consecutive runs produce byte-identical artifacts.
