# Contributing

Thank you for helping keep New World playable on private infrastructure after
the official shutdown (**2027-01-31**). Read [`docs/LEGAL.md`](docs/LEGAL.md)
before you open a PR or share captures.

## What we want

- Protocol facts with evidence. A new field name lands in
  `research/atlas/meanings.md` before any code encodes it.
- Rust only after that file names the fields. The shape is in `docs/PLAN.md`.
  There is no `server/` tree until then.
- Docs that shrink chaos: short STATUS, ADRs for irreversible choices.
- Tests and harnesses that prove a claim.

## What we reject

- Copyrighted game assets, Steam trees, or ripped media.
- Amazon server binaries or leaked source.
- Raw session dumps with live tokens in the git tree.
- “LLM verified” atlas facts without a second signal.
- Branding that claims Amazon affiliation or impersonates other fan projects.

## How to work

Follow [`docs/runbooks/contributor-loop.md`](docs/runbooks/contributor-loop.md).

1. `python ef.py setup --core` then `python ef.py doctor` (add `--re` only if
   you need Ghidra). Purge leftovers with `python ef.py setup --purge`.
2. Prefer a focused branch; keep PRs reviewable.
3. Update the atlas / ontology when you learn a wire fact — chat is not durable.
4. Keep `STATUS.md` ≤ ~80 lines; put diaries under `docs/journal/raw/`.
5. Do not add a Rust crate for a message whose fields are still unknown.
6. Tests must encode a **real failure mode or player-visible outcome** (ADR
   0007). No decorative getter tests.
7. Funding ideas must follow [`docs/LEGAL.md`](docs/LEGAL.md) §Funding — no
   pay-to-win, no Amazon assets for sale.

## Captures

- Record only on your private stack or with clear personal risk acceptance.
- Scrub tokens before upload. Prefer summaries and fixtures over full pcaps
  in PRs.
- Name the client build SHA-256 every time.

## License & DCO

Public open-source license and Developer Certificate of Origin (or CLA) land
when the GitHub-open gate (master plan P22) is met. Until then, by submitting
a contribution you confirm you have the right to submit it and that the
project may distribute it under the eventual project license.

## Conduct

Be respectful. No harassment. No trafficking in stolen accounts or paid cheats.
Preservation is the mission — not griefing Amazon players while official
servers remain online.
