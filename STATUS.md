# Live status

Frontier only. Diary:
[`docs/journal/raw/2026-10-status-dump.md`](docs/journal/raw/2026-10-status-dump.md).
Platform: [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md).
Agent OS: [`.agents/README.md`](.agents/README.md).
Daily loop: **`az.py dev`** (ADR 0009). Branch: `refactor/knowledge-os` (push OK; no PR).

## Active blocker

**Presence layouts identified, not decoded** (`presence-codecs.json`). Next:
live unmarshal → ontology `layout` (after boot-naming coverage).

Build: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Ready for agents

Reorg + ontology seeds + skills/prompts + **scripts by kind**
(`python az.py run list`). Next campaign:
[`docs/runbooks/agentic-boot-campaign.md`](docs/runbooks/agentic-boot-campaign.md).

## Next useful step

1. Run boot-naming campaign (HTTPS + ladder + presence uids at least `bytes`).
2. Presence layout live decode; Rust domain spawn on `az.py dev`.
3. MSVC OpenSSL (`az doctor`); rename lock (ADR 0005).

## Do not

- PR theater until public open; Compose for daily Windows client loop.
- Reload journal raw; ship PAKs; claim Amazon affiliation.
