# Vendored: rust-review

Upstream: https://github.com/morganlinton/BeautifulRust
Pinned commit: `2b2d53a66f6f36ab4b8d6a93070183d91e77fad4`
Version: 1.2.0
License: MIT (see `LICENSE`)
Vendored on: 2026-10-25

## What was copied

- `SKILL.md`
- `LICENSE`

Not copied: `evals/`, `.claude-plugin/`, `assets/`, the top-level `README.md`.

This skill reads `../rust-best-practices/references/` when it needs the full
reasoning behind a rule. Both are vendored together on purpose; installing one
without the other degrades the report's citations.

## Local patches

None. This file is upstream verbatim.

## Precedence

Everfall's own rules win over this skill wherever they disagree. A finding that
cites an upstream rule but breaks `docs/PLAN.md` or `research/atlas/meanings.md`
is not a finding. The binding statement is in [`../rust/SKILL.md`](../rust/SKILL.md),
section "Precedence".

## What it is used for here

A review report, never a rewrite. When it runs in this project, the reviewer
also has to answer the two questions upstream does not know about:

- Does every encoded field have a name in `research/atlas/meanings.md`?
- Does the change keep I/O out of the simulation crate?
