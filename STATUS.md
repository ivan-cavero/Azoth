# Azoth — live status

Last updated: 2026-09-30. This is the short project dashboard; detailed world findings live in [WORLD-INVESTIGATION.md](research/docs/WORLD-INVESTIGATION.md).

## Current blocker

- Latest fresh run PID 39172, REP session 1059 (2026-09-30 14:29Z): loaded `NewWorld_VitaeEterna`, drained 26 messages, initialized `GDERenderManager`, then stayed black and logged `State(InGame) is timeout`. The record-1 state slot changed null→non-null; manager `+0x08/+0x10` stayed null. Read-only hooks counted 39 manager dispatches (all status 2), zero context-setter calls, zero local-player prototype-builder calls, and zero known actor-factory calls. Deferred queues were empty at every sampled drain entry. Evidence: `research/sessions/world_20260930T143111Z_pid39172_session1059/`.
- Controlled A/B PID 45476/session 1058 set `javelin.deferred-actions-max-depth` from 0 to 16 before world entry. Recursion warnings continued and the frame still went black; that cvar alone does not fix the missing context/actor. Session 1059 has full REP/probe evidence but no HTTP rows, so it is not HTTP-shape evidence.
- Each world A/B needs a fresh `NewWorld.exe`. A failed attempt destroys `ClientContext`; retrying in the same process produces misleading results.
- Do not use Frida or ReadProcessMemory while EAC is active. Use static analysis and server-side capture unless a private runtime without EAC is confirmed.

## Start here

1. Read [the world investigation](research/docs/WORLD-INVESTIGATION.md) for the measured frontier and closed hypotheses.
2. Use [the decompilation workflow](research/docs/DECOMPILATION.md) and keep Ghidra's `decomp.py --serve` running during a RE session.
3. Keep confirmed wire facts in `research/atlas/`; confirmed function addresses in `research/derived/symbols.json`.
4. For each live A/B, start from one fresh game process and keep the matching `Game.log` and `services/world/rep_traffic.jsonl`; see [World debugging](research/docs/WORLD-DEBUGGING.md).

## Project map

- `services/`: gateway, REP/DTLS world server, launcher.
- `research/atlas/`: source of truth for endpoints, models, errors, levers, and observed traffic.
- `research/tools/reversing/`: static analysis and Ghidra automation; outputs go under ignored `research/derived/`.
- `scripts/`: game launch/input helpers and focused instrumentation; see [script index](scripts/README.md).
- `docs/`: project orientation and archived sessions; `research/docs/INDEX.md` is the RE entry point.

Historical sessions stay in `docs/sessions/`. Do not commit or overwrite existing user changes without an explicit request.
