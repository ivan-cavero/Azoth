# Live status

Frontier only. Diary:
[`docs/journal/raw/2026-10-status-dump.md`](docs/journal/raw/2026-10-status-dump.md).
Platform: [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md).
Agent OS: [`.agents/README.md`](.agents/README.md).
Daily loop: **`az.py dev`** (ADR 0009). Branch: `refactor/knowledge-os` (push OK; no PR).

## Ready? (honest)

| Layer | State |
| --- | --- |
| Docs / ADRs / agents / scripts / RE / CI | **Ready** |
| Windows `worldd` via `az.py cargo` | **Ready** |
| Presence wire emit (AddActor AOI fanout) | **Wired** (candidate guid head) |
| Playable multiplayer / render | **Not ready** — meanings + client slice still open |

## Active blocker

**Prove AddActor head == spawn ActorGuid live; SpawnActors u64 meaning.**
`worldd` now fans out composed `msg.add-actor` after the entry ladder
(zeros in undecoded fields). Do not treat that as “players see each other.”

Build: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Next useful step

1. Live session: two clients or probe — unmarshal errors on AddActor fanout?
2. Decode `SpawnActorsMsg` u64 meaning; emit only with evidence.
3. Keep capture spawn until InGame holds with presence on the wire.

## Do not

- PR theater; Compose for daily Windows loop; journal novels; ship PAKs.
- Claim presence render works (client remoteplayer slice still broken).
