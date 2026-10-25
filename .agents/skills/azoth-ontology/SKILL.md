---
name: azoth-ontology
description: Create or promote Everfall atlas ontology concepts (uids, confidence, evidence, indexes) when naming messages, endpoints, flows, or commands. Also update research/atlas/meanings.md when the concept is something the server sends.
---

# Ontology skill

Use whenever you add or change a concept under
`research/atlas/ontology/concepts/`.

## Schema

- One file per uid: `concepts/<uid>.json`
- Must validate against `research/atlas/ontology/schema.json`
- Required: `uid`, `kind`, `name`, `summary`, `confidence`, `status`, `evidence[]`
- Confidence: `bytes` → `layout` → `semantics` → `authoritative`
- Status: `unknown` → `candidate` → `verified` → `implemented` → `retired`
- LLM-only claims stay `candidate` with evidence `type: guessed` until a second signal

## Always update indexes

After adding/removing uids:

- `indexes/by-uid.json`
- `indexes/by-kind.json`
- `indexes/by-wire.json` when a wire id exists

## Campaign default

Post-reorg coverage campaign:
[`docs/runbooks/agentic-boot-campaign.md`](../../../docs/runbooks/agentic-boot-campaign.md)
— name open → InGame before deep combat RE.

## Do not

- Duplicate facts into STATUS or chat instead of ontology.
- Invent wire offsets; put layouts in wire crates / field maps with evidence.
- Promote to `verified` / `authoritative` without capture, live, or decompile proof.
