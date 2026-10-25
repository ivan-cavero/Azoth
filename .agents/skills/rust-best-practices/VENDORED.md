# Vendored: rust-best-practices

Upstream: https://github.com/morganlinton/BeautifulRust
Pinned commit: `2b2d53a66f6f36ab4b8d6a93070183d91e77fad4`
Version: 1.2.0
License: MIT (see `LICENSE`)
Vendored on: 2026-10-25

## What was copied

- `SKILL.md`
- `references/` (5 digests: Google Rust Style Guide, Rust API Guidelines,
  Effective Rust, Rust Design Patterns, Microsoft Pragmatic Rust Guidelines)
- `LICENSE`

Not copied: `evals/`, `.claude-plugin/`, `assets/`, the top-level `README.md`.
Those are upstream packaging, not agent instructions.

## Local patches

None. This file is upstream verbatim.

## Precedence

Everfall's own rules win over this skill wherever they disagree. The binding
statement is in [`../rust/SKILL.md`](../rust/SKILL.md), section "Precedence".
Read that before applying a rule from here to `everfall-*` crates.

## Updating

1. Read the upstream `CHANGELOG.md` between the pinned commit and the target.
2. Re-copy `SKILL.md` and `references/`, then bump the commit above.
3. Check whether the lints in [`../rust/lints/`](../rust/lints/) need to follow
   a new machine-checkable rule.
