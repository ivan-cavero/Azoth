# Research docs — index

**Entry order for a new session.** Two parallel tracks own the live frontier:

1. **Play and measure** (world entry, movement, reconnection): read [STATUS.md](../../STATUS.md)
   first, then [WORLD-DEBUGGING.md](WORLD-DEBUGGING.md) and [WORLD-INVESTIGATION.md](WORLD-INVESTIGATION.md).
2. **Decompile and keep the method** (corpus, PAK/data, protocol corpus, tooling): read
   [DECOMP-PLAN.md](DECOMP-PLAN.md) (why + layers), then [DECOMP-BACKLOG.md](DECOMP-BACKLOG.md)
   (what is open, in order), then [DECOMPILATION.md](DECOMPILATION.md) (tool procedure).
   RE facts land in the atlas (`../atlas/`) and `../derived/symbols.json` at the moment of
   discovery — chat-only findings do not exist.

| Doc | What it covers |
| --- | --- |
| [DECOMP-PLAN.md](DECOMP-PLAN.md) | Long-term program: code corpus, PAK index, named loaders, protocol captures. Read this first if a session was cut |
| [DECOMP-BACKLOG.md](DECOMP-BACKLOG.md) | **Everything still open**, grouped by layer, with blockers and a suggested order. Start here to pick up work |
| [PAK-FORMAT.md](PAK-FORMAT.md) | Measured PAK container facts: what is a ZIP, what method 15 is, what is ruled out |
| [ANALYSIS.md](ANALYSIS.md) | How the client is built: Lumberyard, Javelin, login, PAKs, GridMate |
| [CAPTURE.md](CAPTURE.md) | Passive capture kit: usage and what to record |
| [EAC.md](EAC.md) | Why there is no ReadProcessMemory while on official |
| [CLIENT_CONTRACT.md](CLIENT_CONTRACT.md) | Hosts, JSON and states the client expects |
| [SESSIONS.md](SESSIONS.md) | What came out of the 2026-09-06 captures |
| [PROTOCOL.md](PROTOCOL.md) | DTLS, Carrier, RMI, spawn |
| [JAVELIN-DISPATCH.md](JAVELIN-DISPATCH.md) | Static map of the client's inbound dispatch pipeline (stream processor rings, type-GUID binding, interface handles) |
| [DECOMPILATION.md](DECOMPILATION.md) | Decompilation workflow: tools, method, findings, tooling landscape, version-to-version survival |
| [DEVELOPMENT-LOOP.md](DEVELOPMENT-LOOP.md) | Evidence-first workflow from reproducible bug to regression; test ladder for future features |
| [WORLD-DEBUGGING.md](WORLD-DEBUGGING.md) | Repeatable fresh-process checklist for the black-screen/world-entry investigation |
| [WORLD-INVESTIGATION.md](WORLD-INVESTIGATION.md) | Detailed measured findings and the current replica/bundle frontier |
| [LESSONS.md](LESSONS.md) | Method errors that cost days (guessing vs decompiling, strict models, seed data, process hygiene) — read before any RE round |
| [REP-PROTOCOL.md](REP-PROTOCOL.md) | Javelin REP wire: DTLS trust bypass, Carrier framing, V3 registration, post-V3 ladder |

Plain-text schemas: `../schemas/live/`. Fixtures: `../fixtures/`. Raw sessions: `../sessions/` (gitignored).
Live RE memory: `../atlas/` (endpoints, models, errors, levers, observed traffic + OpenAPI).
