# Live status

Frontier only. Diary:
[`docs/journal/raw/2026-10-status-dump.md`](docs/journal/raw/2026-10-status-dump.md).
Platform: [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md).
Agent OS: [`.agents/README.md`](.agents/README.md).
Daily loop: **`az.py dev`** (ADR 0009). Branch: `refactor/knowledge-os` (push OK; no PR).

## Ready? (honest)

| Layer | State |
| --- | --- |
| Docs / ADRs / agents / scripts / RE tools | **Ready** |
| Ontology seeds (HTTPS, ladder, presence ids) | **Ready** |
| Authoritative play path (`worldd` on wire) | **Not ready** — still capture spawn + Python play loop |
| Windows `worldd` link | **OK via `python az.py cargo`** (GNU+MSYS); bare cargo may mix WinLibs |

Reorg ≠ playable. Agents can name/boot-campaign; gameplay still needs presence meanings + compose on wire + OpenSSL MSVC.

## Active blocker

**Presence meanings + S2C on the wire.** Layouts + `worldd::presence` seed exist.
Ladder still sends capture spawn bundle. Prove field semantics; emit
`SpawnActors`/`AddActor` for AOI; Replicate component codecs.

Build: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Next useful step

1. Live/capture proof: AddActor `head16` / SpawnActors `u64` meanings.
2. Put composed presence on an AOI path (keep capture spawn until InGame holds).
3. `az doctor`: one OpenSSL path (MSVC + vcpkg); clear MinGW `OPENSSL_DIR` for MSVC rustc.

## Do not

- PR theater until public open; Compose for daily Windows client loop.
- Reload journal raw; ship PAKs; claim Amazon affiliation.
- Treat knowledge reorg as “server done.”
