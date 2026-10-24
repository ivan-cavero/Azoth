---
name: azoth-knowledge
description: Keep Azoth STATUS, ADRs, runbooks, and docs navigable for agents; enforce STATUS budget and never reload journal novels.
---

# Knowledge / docs skill

Use when editing `STATUS.md`, `docs/`, ADRs, runbooks, or agent catalogs.

## Hard budgets

- `STATUS.md` ≤ ~80 lines (`python az.py run check-docs`).
- Diaries → `docs/journal/raw/` — **never** `Read` whole raw dumps; grep with head limit.
- Public roadmap = `site/src/data/roadmap-v2.ts` only (v1 archived).
- Product vision = `docs/PLAN-master-platform.md`; tick/wire = `PLAN-backend-rust.md`.
- Scripts: `scripts/<kind>/` + `catalog.json`; `python az.py run list`.

## ADR rule

Irreversible choices (crypto, naming, funding, native-vs-compose, testing) get
an ADR under `docs/adr/`. Update `docs/adr/README.md`.

## Agent catalog

Keep `.agents/README.md`, `prompts/README.md`, and skill frontmatter in sync
when adding prompts/skills.

## After edits

```text
python az.py run check-docs
python az.py run check-paths
python az.py run check-scripts
```
