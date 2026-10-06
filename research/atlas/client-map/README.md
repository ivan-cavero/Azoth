# Client map (growing knowledge plan)

This is the per-screen knowledge base that decompilation and protocol agents
fill in as they work. The [campaign manifest](../decomp-campaign.json) tracks
what has been decompiled; this folder records what was **learned**, referenced
to evidence files. One file per player-visible phase, in order:

1. [`launch.md`](launch.md) — engine startup, title screen, settings bootstrap
2. [`login.md`](login.md) — Steam auth, gateway queue, login RMI chain
3. [`server-select.md`](server-select.md) — server list and selection
4. [`character-select.md`](character-select.md) — list/create/delete character
5. [`world-entry.md`](world-entry.md) — REP connection, V3, spawn ladder
6. [`in-world.md`](in-world.md) — movement/physics, interaction, menus, zoning

## Rules

- Follow the template in [`TEMPLATE.md`](TEMPLATE.md). Add subsections freely;
  do not delete other agents' findings.
- Every claim links its evidence: a decompiled file under the ignored build
  workspace (`reverse/builds/<sha256>/campaign/<phase>/<va>.c`), an atlas entry
  (`client-functions.json`, `models.json`), a Game.log ingest, a capture, or a
  ticket/fixture. Label claims `observed` / `statically-derived` / `validated`
  / `guessed` — see the atlas evidence rules in [`../README.md`](../README.md).
- Record interactables exhaustively: buttons, menus, sliders, drag targets,
  keyboard shortcuts — **and non-obvious surfaces**: developer/console
  commands, hidden settings, debug UI, telemetry pings, endpoints the screen
  calls that are undocumented elsewhere.
- A decompiled `.c` file is pseudocode, not proof. A claim becomes
  `validated` only with a second independent signal (runtime log, wire
  capture, reflection registration, byte pattern).
- Client-build-specific addresses belong in `client-functions.json`; this
  folder holds behavior that survives re-derivation. Never paste secret
  material here; raw captures stay in ignored `research/sessions/`.
- When a phase file gets large, split by topic (`in-world-movement.md`, ...)
  and link it from the phase file's overview.

## Workflow

1. Pick the phase in `python az.py re campaign status` with pending work.
2. Decompile a batch, read the `.c` output under the build workspace.
3. Write findings into the phase file with evidence links; add new function
   discoveries to the campaign phase (`campaign add` / `expand`) and confirmed
   names to `client-functions.json`.
4. Repeat. A phase overview is "current" when every subsection has either
   findings with evidence or an explicit `open:` question.
