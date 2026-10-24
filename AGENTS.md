# Azoth agent instructions

Short invariants only. Nearest nested `AGENTS.md` wins for package details.
North star: [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md).

## Read first

| Need | File |
| --- | --- |
| Frontier (≤80 lines) | [`STATUS.md`](STATUS.md) |
| Diary archive | [`docs/journal/`](docs/journal/) |
| Platform / reorg / agents | [`docs/PLAN-master-platform.md`](docs/PLAN-master-platform.md) |
| Rust crates / tick | [`docs/PLAN-backend-rust.md`](docs/PLAN-backend-rust.md) |
| Thin architecture | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Ontology facts | [`research/atlas/ontology/`](research/atlas/ontology/) |
| Legal / collab | [`docs/LEGAL.md`](docs/LEGAL.md), [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Boot-naming campaign | [`docs/runbooks/agentic-boot-campaign.md`](docs/runbooks/agentic-boot-campaign.md) |
| Agent OS catalog | [`.agents/README.md`](.agents/README.md) |
| Skills | [`.agents/skills/`](.agents/skills/) |
| Prompts | [`.agents/prompts/README.md`](.agents/prompts/README.md) |

## Hard rules

- Durable facts → `research/atlas/` (ontology for purpose; JSON registries for wire). Chat/STATUS are not enough.
- Mark guesses `"evidence": "guessed"`. LLM output is `candidate` until a second signal.
- Full client SHA-256 before trusting a VA/offset. Corpora under `reverse/builds/<sha256>/`.
- Never Frida/RPM/debugger while EAC state is uncertain. Azoth launches without EAC; still verify.
- Steam install is read-only. Private runtime under `private-client/`; tools under `.azoth/`.
- `python az.py` / `.\az.ps1` owns lifecycle. No machine-specific user paths in git.
- Keep `STATUS.md` ≤ **80 lines** (`python az.py run check-docs`). Diaries → `docs/journal/`.
- New helpers go under `scripts/<kind>/` + `scripts/catalog.json` — never a flat dump.
- **Never** `Read` whole files under `docs/journal/raw/` — grep with a head limit.
- **Never** re-serve `site/src/data/archive/roadmap-v1-inventory.ts` on the landing page.
- Code you add must be **called** and map to an ontology purpose; no dead crates or decorative types.
- One winning runtime behaviour; delete losers; keep negatives in atlas.
- Do not commit or push unless the user asks.
- Domain code must not invent wire offsets; codecs live in `azoth-wire` / ontology field maps.
- No New World PAKs/assets in git; do not claim Amazon affiliation; brand rename pending (ADR 0005).
- OpenSSL stays inside `azoth-dtls` (ADR 0004); public binary name is `world` (ADR 0006).
- Daily loop is native `az.py dev` (ADR 0009); Compose is Linux/CI only.

## Nested instructions

| Tree | File |
| --- | --- |
| Rust server | [`server/AGENTS.md`](server/AGENTS.md) |
| Research / atlas | [`research/AGENTS.md`](research/AGENTS.md) |
| Reverse engineering | [`reverse/AGENTS.md`](reverse/AGENTS.md) |
| Python services | [`services/AGENTS.md`](services/AGENTS.md) |

## Handoff

State observed vs inferred, build SHA, evidence paths, validation done/not done,
failed hypotheses, and the next concrete blocker. Update atlas/ontology before
declaring done.
