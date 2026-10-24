# Boot naming campaign

Use when the user asks to name systems/messages from game open through InGame,
or to run the post-reorg ontology coverage campaign.

## Task

From process start to InGame on the pinned client build, assign durable names
(ontology uids + atlas facts) to every meaningful surface on the critical path.
Follow [`docs/runbooks/agentic-boot-campaign.md`](../../docs/runbooks/agentic-boot-campaign.md).

## Rules

- Read `STATUS.md`, `AGENTS.md`, `research/AGENTS.md` first.
- One concept file per uid under `research/atlas/ontology/concepts/`.
- Mark guesses `"type": "guessed"` in evidence; never promote alone.
- Full SHA-256 before trusting VA/offset.
- Do not Frida/RPM while EAC uncertain.
- Do not commit unless asked.
- Prefer boot/presence over deep combat until the coverage gate passes.

## Output

- Updated ontology concepts + indexes.
- Short STATUS frontier update (still ≤80 lines).
- List of remaining unnamed critical-path items.
