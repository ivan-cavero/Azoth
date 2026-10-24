# research/ agent notes

Durable knowledge. Root [`AGENTS.md`](../AGENTS.md) still applies.

## Where facts go

| Kind | Home |
| --- | --- |
| Purpose / lifecycle / confidence | `atlas/ontology/concepts/*.json` |
| Wire registries, endpoints, functions | `atlas/*.json` (existing) |
| Screen map | `atlas/client-map/` |
| Deep protocol writeups | `docs/` under research |
| Raw captures / secrets | `sessions/` (gitignored) |

## Rules

- One fact → one ontology or registry home; link from STATUS/docs, do not copy.
- Confidence: `bytes` → `layout` → `semantics` → `authoritative`.
- Status: `unknown` → `candidate` → `verified` → `implemented` → `retired`.
- LLM may write `candidate` / `unknown` only. Promote with a second signal.
- Always record full build SHA when binary-dependent.
- Schema: `atlas/ontology/schema.json`.
