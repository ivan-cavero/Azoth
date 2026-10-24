# reverse/ agent notes

Static and live client analysis. Root [`AGENTS.md`](../AGENTS.md) still applies.
Skill: [`.agents/skills/azoth-re/SKILL.md`](../.agents/skills/azoth-re/SKILL.md).

## Rules

- Isolate all generated output under `builds/<full-sha256>/` (gitignored).
- Prefer xref → strings/reflection → targeted decompile (`az.py re …`).
- Pseudocode is not verified source. Confirmed names → `research/atlas/client-functions.json`.
- AI annotations stay under `builds/<sha>/ai/` until promoted.
- Never attach Frida/debugger if EAC state is uncertain.
- Presence layouts on 1.460 need live unmarshal (runtime-built descriptors).
