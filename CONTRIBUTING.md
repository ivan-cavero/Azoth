# Contributing

Thank you for helping keep New World playable on private infrastructure after
the official shutdown (**2027-01-31**). Read [`docs/LEGAL.md`](docs/LEGAL.md)
before you open a PR or share captures.

## What we want

- Protocol facts with evidence (atlas / ontology promotions).
- Authoritative server behaviour in Rust (`server/`) that uses domain types,
  not new magic offsets in app code.
- Docs that shrink chaos: short STATUS, ADRs for irreversible choices.
- Tests and harnesses that prove a claim.

## What we reject

- Copyrighted game assets, Steam trees, or ripped media.
- Amazon server binaries or leaked source.
- Raw session dumps with live tokens in the git tree.
- “LLM verified” atlas facts without a second signal.
- Branding that claims Amazon affiliation or impersonates other fan projects.

## How to work

1. Prefer a focused branch; keep PRs reviewable.
2. Update the atlas / ontology when you learn a wire fact — chat is not durable.
3. Keep `STATUS.md` ≤ ~80 lines; put diaries under `docs/journal/raw/`.
4. For Rust: put meaning in `azoth-model` (and future sim/replica); put bytes in
   `azoth-wire`; keep DTLS inside the DTLS crate.
5. Run what you can locally (`scripts/check-docs.py`, crate tests). Full
   `worldd` tests need a documented OpenSSL toolchain on Windows — see
   `server/AGENTS.md`.

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
