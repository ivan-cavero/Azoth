# Agentic campaign: name everything from boot

First post-reorg RE campaign. Goal: from **process start → character select →
InGame**, every meaningful client system, message, and endpoint gets a stable
ontology uid and atlas fact — nothing anonymous.

## Preconditions

- Branch reorg landed; `python az.py doctor` core OK.
- Build SHA pinned in `STATUS.md` / `research/atlas/builds.json`.
- Private client available; EAC state verified (Azoth launch without EAC —
  still verify). No Frida while uncertain.
- Agents: root `AGENTS.md` + `research/AGENTS.md` + `reverse/AGENTS.md`.
  Prompt: `.agents/prompts/boot-naming-campaign.md`.

## Loop (repeat until coverage gate)

1. **Pick the next unnamed surface** in boot order (launcher HTTPS → region →
   DTLS → REP ladder → presence). Prefer STATUS blocker when set.
2. **Observe** (capture / decompile / live — only the allowed tool).
3. **Name** in ontology (`research/atlas/ontology/concepts/<uid>.json`) with
   confidence `bytes|layout|semantics` and evidence refs. Update indexes.
4. **Wire map** in atlas registries if it is a message/endpoint.
5. **Server note:** if the Rust path already sends/receives it, set
   `owners.crate` / `module`; else leave null and link STATUS.
6. **Handoff** one paragraph in STATUS (≤80 lines total file): what named,
   what blocked, next uid.

## Coverage gate (campaign “done enough” to resume world entry work)

- All ladder rungs have ontology uids (already started).
- All presence wire ids in `presence-codecs.json` have concept files at least
  `confidence: bytes`.
- HTTPS boot endpoints used on private path have `endpoint.*` concepts or
  atlas endpoint rows linked from ontology.
- Zero “mystery blob” on the critical path without a `uid` + evidence.

## Anti-patterns

- Naming from LLM memory without a second signal.
- Skipping indexes / schema fields.
- Writing novels into STATUS.
- Starting combat/economy RE before boot/presence named.

## After this campaign

Resume Rust domain lift: compose spawn from model, enter world with practices
in ADR 0007 / server AGENTS — still via **`az.py dev`**, not Compose
(ADR 0009).
