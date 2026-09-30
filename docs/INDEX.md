# Documentation — index

**Azoth** — New World private server. RE knowledge lives in **research/** (atlas + docs), the server contract in **services/docs/**, the own-client in **services/launcher/**. This `docs/` is the glue. All docs are written in English; `docs/archive/` and `docs/sessions/` hold Spanish historical documents.

## System

| Doc | Content |
| --- | --- |
| [NOMBRE.md](NOMBRE.md) | Why "Azoth" |
| [ROADMAP.md](ROADMAP.md) | Phases + **what to capture now** |
| [ADMIN.md](ADMIN.md) | **Admin permissions: ask the operator for UAC ONCE before starting** (Spanish) |
| [sessions/](sessions/) | Historical session log (`2026-09-13_pre-monorepo-STATUS.md` = the full pre-monorepo STATUS) |
| [archive/](archive/) | Pre-monorepo design docs (Spanish, old paths — design rationale only) |
| [../services/docs/PERFORMANCE.md](../services/docs/PERFORMANCE.md) | Density / tick / AOI |

## Research (`research/docs/`)

| Doc | Content |
| --- | --- |
| [ANALYSIS.md](../research/docs/ANALYSIS.md) | Engine, login, GridMate, PAKs |
| [CAPTURE.md](../research/docs/CAPTURE.md) | Passive capture kit |
| [EAC.md](../research/docs/EAC.md) | EAC EOS, no process memory while on official |
| [CLIENT_CONTRACT.md](../research/docs/CLIENT_CONTRACT.md) | JSON/hosts the client expects |
| [SESSIONS.md](../research/docs/SESSIONS.md) | Live 2026-09-06 findings |
| [PROTOCOL.md](../research/docs/PROTOCOL.md) | DTLS, Carrier, RMI |
| [DECOMPILATION.md](../research/docs/DECOMPILATION.md) | Decompilation workflow (tools, method, findings) |
| [DEVELOPMENT-LOOP.md](../research/docs/DEVELOPMENT-LOOP.md) | Reproducible evidence, fast test ladder, and regression workflow for all future features |
| [WORLD-DEBUGGING.md](../research/docs/WORLD-DEBUGGING.md) | Fresh-process checklist for the current black-screen investigation |
| [WORLD-INVESTIGATION.md](../research/docs/WORLD-INVESTIGATION.md) | Detailed world-entry evidence and current frontier |

**Atlas (live RE memory):** [`research/atlas/`](../research/atlas/README.md) — endpoints, wire models, errors, debug levers, observed traffic + OpenAPI.
Live schemas: `research/schemas/live/`. Fixtures: `research/fixtures/`. Working RE notes: `research/notes/`.

## Services (`services/docs/`)

| Doc | Content |
| --- | --- |
| [GATEWAY.md](../services/docs/GATEWAY.md) | HTTPS :8080 |
| [WORLD.md](../services/docs/WORLD.md) | REP / spawn |
| [DATA.md](../services/docs/DATA.md) | Persistence (note: today DB-free, mocks) |

## Launcher (`services/launcher/docs/`)

| Doc | Content |
|---|---|
| [LAUNCHER.md](../services/launcher/docs/LAUNCHER.md) | Updater, Play, no Steam |
