# Azoth

Private server for **New World: Aeternum**. Azoth is the essence of the world in the game; here it is the name of the project and of the world.

The client you already own is not cracked: it is spoken to in its own language (TrinityCore model). In **private** mode it launches **without Easy Anti-Cheat** and **without Steam**, with our own launcher.

Single monorepo (no git submodules). Pre-monorepo history lives in the archived `Azoth-Research` / `Azoth-Emulator` / `Azoth-Launcher` repos and in the `archive/pre-monorepo` branch.

## Layout

| Folder | What it is |
| --- | --- |
| [`az.py`](az.py) | **Single CLI**: `python az.py gateway start` · `gateway reload` (hot-reload dev) · `gateway test` · `caddy` · `game` · `mode private` · `shot` · `click` · `key` · `shape` · `doc` |
| [`services/`](services/) | Services: `gateway/` (HTTPS :8080, stdlib Python, full traffic capture), `world/` (REP/DTLS, pending), `launcher/` (Steam stub + client launch) |
| [`research/`](research/) | RE: **atlas** (endpoints, wire models, errors, debug levers, observed traffic + OpenAPI), method docs, tools (xrefmap, Ghidra headless, passive capture), live schemas |
| [`deploy/`](deploy/) | Caddy :443, certs, host allowlist, official/private switch |
| [`scripts/`](scripts/) | Live game instrumentation: OCR, synthetic click, input, A/B shape harness |
| [`docs/`](docs/) | Architecture + historical sessions |

## Two profiles, never mixed

**Official** (record Amazon until 2027-01-31): Steam → Amazon launcher → EAC → vanilla exe. Clean hosts. Kit: `research/tools/capture`.

**Private** (Azoth): our launcher → `Bin64\NewWorld.exe` directly. Talks only to `services/gateway`. No exe patches.

## Development loop

Start from [`STATUS.md`](STATUS.md) for the current frontier. Use
[`research/docs/DEVELOPMENT-LOOP.md`](research/docs/DEVELOPMENT-LOOP.md) to
reproduce bugs, capture evidence, choose the fastest decisive test, and keep a
regression for each fix. Current world-entry case:
[`WORLD-DEBUGGING.md`](research/docs/WORLD-DEBUGGING.md) and
[`WORLD-INVESTIGATION.md`](research/docs/WORLD-INVESTIGATION.md). The script
entry points are indexed in [`scripts/README.md`](scripts/README.md).

## State

`STATUS.md` (lean) + `research/atlas/` (RE memory). Historical sessions in `docs/sessions/`.

## Agent rules

`AGENTS.md` — RE method, test loop, atlas discipline, conventions.
