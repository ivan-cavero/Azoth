> This prompt is not the driver. Read `STATUS.md` and `.agents/skills/everfall-next/SKILL.md`. The Rust tree `server/` was deleted. Do not recreate it from these steps.

# Ontology promote

Use when the user asks to name, register, or promote a client/server concept
into the atlas ontology.

## Task

Turn an observed surface (message, endpoint, flow, command, system) into a
durable ontology concept with evidence, then update indexes.

## Required skill

Read `.agents/skills/azoth-ontology/SKILL.md` before writing files.

## Steps

1. Confirm build SHA if binary-dependent.
2. Search existing `concepts/` and atlas JSON — do not duplicate uids.
3. Write `concepts/<uid>.json` per schema.
4. Update `indexes/by-uid.json` and `by-kind.json` (and `by-wire.json` if needed).
5. If the server already owns behavior, set `owners.crate` / `module`.
6. Touch `STATUS.md` only if this was the active blocker / next step.

## Acceptance

- Schema fields present; evidence has at least one non-empty `ref`.
- Indexes list the uid.
- Confidence/status honest (no silent `authoritative`).
