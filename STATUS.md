# Live status

Frontier only. Diary:
[`docs/journal/raw/2026-10-status-dump.md`](docs/journal/raw/2026-10-status-dump.md).
Platform: [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md).
Agent OS: [`.agents/README.md`](.agents/README.md).
Daily loop: **`az.py dev`** (ADR 0009). Branch: `refactor/knowledge-os` (push OK; no PR).

## Active blocker

**Presence field meanings + worldd compose.** Fixed layouts live in
`azoth-wire::presence` + ontology (`layout` for 449/574/422/106).
Still open: prove field semantics; emit composed AddActor/Spawn from
`worldd` (not capture templates); Replicate component codecs.

Build: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Ready for agents

Reorg done. Boot-naming: HTTPS endpoints + ladder rungs + presence wire
ids named. Next: meanings / compose spawn via
[`docs/runbooks/agentic-boot-campaign.md`](docs/runbooks/agentic-boot-campaign.md).

## Next useful step

1. Compose spawn path in `worldd` using `azoth-wire` presence + `azoth-model`.
2. Live or capture proof for AddActor head16 / SpawnActors id meanings.
3. MSVC OpenSSL (`az doctor`); rename lock (ADR 0005).

## Do not

- PR theater until public open; Compose for daily Windows client loop.
- Reload journal raw; ship PAKs; claim Amazon affiliation.
