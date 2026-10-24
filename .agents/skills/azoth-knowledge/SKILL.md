---
name: azoth-knowledge
description: Keep Azoth STATUS, ADRs, runbooks, and docs navigable for agents; enforce STATUS budget and never reload journal novels.
---

# Knowledge / docs skill

Use when editing `STATUS.md`, `docs/`, ADRs, runbooks, or agent catalogs.

## Hard budgets

- `STATUS.md` ≤ ~80 lines (`python scripts/check-docs.py`).
- Diaries → `docs/journal/raw/` — **never** `Read` whole raw dumps; grep with head limit.
- Public roadmap = `site/src/data/roadmap-v2.ts` only (v1 archived).
- Product vision = `docs/PLAN-master-platform.md`; tick/wire = `PLAN-backend-rust.md`.

## ADR rule

Irreversible choices (crypto, naming, funding, native-vs-compose, testing) get
an ADR under `docs/adr/`. Update `docs/adr/README.md`.

## Agent catalog

Keep `.agents/README.md`, `prompts/README.md`, and skill frontmatter in sync
when adding prompts/skills.

## After edits

```text
python scripts/check-docs.py
python scripts/check-paths.py
```
