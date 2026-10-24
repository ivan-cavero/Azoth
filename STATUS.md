# Live status

Frontier only. Diary:
[`docs/journal/raw/2026-10-status-dump.md`](docs/journal/raw/2026-10-status-dump.md).
Platform: [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md).
Rust: [`docs/PLAN-backend-rust.md`](docs/PLAN-backend-rust.md).
Legal: [`docs/LEGAL.md`](docs/LEGAL.md). Official NW offline: **2027-01-31**.

## Active blocker

**Presence layouts are identified, not decoded.** Six actor-replication message
types live in `research/atlas/presence-codecs.json` (wires 449, 574, 391, 407,
422, 106). Descriptor tables are assembled at runtime on build 1.460 — static
xref routes that worked for movement on 1.400 do not apply. Next unit: live
unmarshal at the type dispatch (`vtable+0x90`) and record layouts into the
ontology / atlas.

Build: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## What is already true

- Private client reaches **InGame** (Python floor; Rust world process is the
  authoritative port — no replay pump).
- Two REP sessions at once; movement / HUD / request gating measured in atlas.
- Branch `refactor/knowledge-os`: Knowledge OS, roadmap v2, `azoth-model`,
  LEGAL/NOTICE/CONTRIBUTING, ADRs 0003–0006 (OpenSSL keep; rename pending;
  public binary name `world`).

## Next useful step

1. Presence unmarshal → ontology `layout`.
2. Retire spawn capture seed via composed domain snapshot.
3. Lock rename shortlist ([ADR 0005](docs/adr/0005-project-rename.md)).
4. Document one Windows OpenSSL toolchain ([ADR 0004](docs/adr/0004-dtls-crypto-stack.md)).

## Do not

- Reload `docs/journal/raw/` into agents; treat chat as the fact store.
- Ship as “Azoth” / claim Amazon affiliation; redistribute PAKs.
- Promote LLM guesses without a second signal.
