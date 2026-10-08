# Research index

## Start here

- [Method lessons](LESSONS.md) — how to avoid repeating failed experiments.
- [Development loop](DEVELOPMENT-LOOP.md) — choosing and measuring a decisive
  experiment.
- [Decompilation](DECOMPILATION.md) — tools and static analysis workflow.
- [Decompilation backlog](DECOMP-BACKLOG.md) — remaining naming, data, and
  protocol work.
- [EAC boundary](EAC.md) — rules for official and private client processes.
- [Private client runbook](PRIVATE-CLIENT-RUNBOOK.md) — cold setup, the five
  gates a private run crosses, patch policy (disk vs Frida, when to apply),
  and where each artifact actually lands.
- [Server contract](SERVER-CONTRACT.md) — phase-by-phase list of what the
  client expects from the server, the REP message registry both directions,
  and what is still missing (movement authority).
- [Javelin message GUIDs](JAVELIN-MESSAGE-GUIDS.md) — the 156 named message
  types with their AZ type GUIDs, including the movement family.
- [Session 2026-10-07/08](SESSION-2026-10-07.md) — autonomous overnight run:
  gates 5-8 closed, stable session, protocol mapped, warning inventory.

## Protocol and client

- [Javelin protocol](JAVELIN-PROTOCOL.md) — consolidated full reference:
  layers, channels, system ids, typed-message registry, measured gaps.
- [REP protocol](REP-PROTOCOL.md) — DTLS, Carrier, and world messages.
- [Client contract](CLIENT_CONTRACT.md) — observed HTTP and client data shapes.
- [World investigation](WORLD-INVESTIGATION.md) — accumulated evidence for
  the current world-entry and movement work.
- [Capture](CAPTURE.md) — official passive capture procedure.
- [PAK format](PAK-FORMAT.md) — measured archive and asset formats.

## Durable data

- `../atlas/` — endpoint models, errors, observed traffic, levers, and confirmed
  client function names.
- `../fixtures/` — redacted inputs suitable for repeatable offline analysis.
- `../sessions/` — raw local session data; ignored by Git.
- `../derived/` — generated catalogs and summaries; local decompilation output
  is ignored. Do not treat a generated pseudocode file as a verified fact.
