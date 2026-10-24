# Azoth agent prompts

Reusable workflows. A prompt does not replace `AGENTS.md` or authorize
unrequested actions. Catalog hub: [`.agents/README.md`](../README.md).

## Choose a role

| Prompt | Use it for | Main output |
| --- | --- | --- |
| [Session driver](autonomous-driver.md) | Any session; picks focused prompt + skills | Verified result + handoff |
| [Boot naming campaign](boot-naming-campaign.md) | Name open → InGame into ontology | Coverage toward campaign gate |
| [Ontology promote](ontology-promote.md) | Single concept create/promote | Concept JSON + indexes |
| [World entry Rust](world-entry-rust.md) | Ticket → InGame on `worldd` | Authoritative entry behaviour |
| [Decompilation review](decompilation-review.md) | Build-scoped RE corpus | Hash-scoped evidence |
| [Protocol analysis](protocol-analysis.md) | Exact wire/state contract | Atlas-backed flow |
| [Server feature development](server-developer.md) | Client-visible gameplay feature | Minimal server behaviour |
| [Live client analysis](live-analysis.md) | Authorized live experiment | Time-correlated finding |
| [Code refactoring](refactor.md) | Simplify implementation/docs | Smaller design, same behaviour |
| [Full project audit](project-audit.md) | Merge-readiness / chaos audit | Severity-grouped fixes |

Use the **session driver** unless the user already named a focused role.
For unknown protocol → protocol analysis → (optional) decompilation → server
feature. Prefer **boot naming** before deep combat RE after the knowledge-OS
reorg.

## Shared rules

- Read root + nested `AGENTS.md`, `STATUS.md`, relevant skill.
- Label observed vs inferred vs guessed; full client SHA when binary-dependent.
- Facts → atlas/ontology. STATUS stays short.
- Native `az.py dev` for private-client work (ADR 0009).
- Do not commit/push unless the user asks (on this private phase, push the
  working branch when asked — no PR required until public open).
