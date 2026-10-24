# Protocol / platform ontology

Scalable fact store for agents. One concept = one JSON file under `concepts/`.
Indexes under `indexes/` are generated or hand-maintained stubs until
`az.py atlas index` exists.

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
