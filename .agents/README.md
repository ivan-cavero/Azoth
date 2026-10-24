# Agent operating system

Everything an agent needs after clone. Short root rules:
[`AGENTS.md`](../AGENTS.md). Frontier: [`STATUS.md`](../STATUS.md).

## Order of operations

1. Read root `AGENTS.md` + nested `*/AGENTS.md` for the tree you touch.
2. Read `STATUS.md` (≤80 lines). Do **not** load `docs/journal/raw/`.
3. Pick **one** prompt from [`prompts/README.md`](prompts/README.md).
4. Read the matching **skill** before that workflow.
5. Daily loop is native `python az.py dev` ([ADR 0009](../docs/adr/0009-native-dev-vs-compose.md)).
6. Durable facts → `research/atlas/ontology/` + atlas JSON — never chat-only.

## Catalog

| Kind | Path |
| --- | --- |
| Prompts | [`prompts/`](prompts/) |
| Skills | [`skills/`](skills/) |
| Overnight loop | [`../docs/runbooks/agent-overnight.md`](../docs/runbooks/agent-overnight.md) |
| Boot-naming campaign | [`../docs/runbooks/agentic-boot-campaign.md`](../docs/runbooks/agentic-boot-campaign.md) |
| Contributor DX | [`../docs/runbooks/contributor-loop.md`](../docs/runbooks/contributor-loop.md) |

## Skills (required reads)

| Skill | When |
| --- | --- |
| [`azoth-ontology`](skills/azoth-ontology/SKILL.md) | Creating/promoting concept uids, indexes |
| [`azoth-re`](skills/azoth-re/SKILL.md) | Decompile, wire schemas, PAK/static RE |
| [`azoth-live-debug`](skills/azoth-live-debug/SKILL.md) | Private-client live experiment |
| [`azoth-computer-use`](skills/azoth-computer-use/SKILL.md) | Drive visible game window |
| [`azoth-server`](skills/azoth-server/SKILL.md) | Rust world/region/channel, domain lift |
| [`azoth-knowledge`](skills/azoth-knowledge/SKILL.md) | STATUS/docs/ADR hygiene, no novels |

## Branch / git (pre-public)

Until the repo is opened to the public (plan P22): **commit and push the
working branch when the user asks** — no PR theater. Do not force-push
`main`. Do not open PRs unless asked.
