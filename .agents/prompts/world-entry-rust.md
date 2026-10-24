# World entry (Rust)

Use when implementing or hardening the path from ticket redeem → InGame on the
authoritative Rust world (`server/apps/worldd`), not the Python prototype.

## Required skill

`.agents/skills/azoth-server/SKILL.md` (+ ontology skill if naming new uids).

## Rules

- Daily loop: `python az.py dev` (ADR 0009) — not Compose.
- Domain types from `azoth-model`; ladder rungs expose `ontology_uid`.
- Capture seeds are temporary; replace with composed domain state when layouts exist.
- Bytes only in `azoth-wire` / DTLS crate. No new magic offsets in app code.
- Tests must encode failure modes (ADR 0007): expired ticket after auth must not
  kick; bad role cannot grant; etc.

## Acceptance

- Observable InGame or a clear measured blocker with atlas/STATUS update.
- `python az.py test e2e entry` still green for offline crates when applicable.
