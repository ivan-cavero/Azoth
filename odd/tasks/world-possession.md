# world-possession — make the client render the world with the local player

Owner feature doc. The long-running blocker was: the client reaches `InGame`,
loads `NewWorld_VitaeEterna`, drains the replay — and renders black, because the
local player is never possessed. Detail lives in
[WORLD-INVESTIGATION.md](../../research/docs/WORLD-INVESTIGATION.md) and
[WORLD-DEBUGGING.md](../../research/docs/WORLD-DEBUGGING.md).

## Why this feature exists

Everything else in the project (movement, combat, inventory, instances) needs the
client to actually be in the world as a player. Until 2026-10-02 it was not.

## Tasks

- [x] T1 — Finish the full-client decompilation corpus so the gate chain can be
      read instead of inferred. Corpus `status=complete`, 423579 functions.
- [x] T2 — Re-read the gate chain from pseudocode and correct the archived
      reading (thread-local option store; empty strings compare equal; two
      setters on status 1).
- [x] T3 — Give the burst probe a live control counter and an attach-verify
      retry loop, so a zero counter can be interpreted.
- [x] T4 — Measure the gate on a fresh process with a verified instrument, and
      locate the compared value on the wire.
- [x] T5 — Implement the targeted local-player UUID substitution
      (`fill_local_player_uuid`) with unit + capture-fixture tests.
- [x] T6 — Verify live: the world renders with the local player possessed.
- [x] T7 — Consolidate: STATUS, atlas lever, WORLD-INVESTIGATION, WORLD-DEBUGGING,
      symbols, world README, scripts README.

## Evidence log

| When | What |
| --- | --- |
| 2026-10-01 | Corpus `status=complete` (423579 functions, 25 `fail`). Gate chain read from pseudocode; archived reading corrected in two places. Pseudocode cached at `research/derived/decomp/gate-chain.c`. |
| 2026-10-01 | Probe fixed (control counters `FUN_1416adce0`/`FUN_145f62e80` + attach retry). First trustworthy measurement: 283 splits/visits, 39 dispatches, 26 writer calls, 26 local lookups HIT, 26 status 2, 0 context setters. |
| 2026-10-01 | Live string samples exposed the compared value: the wire UUID is all zeros while the local store holds the character UUID. |
| 2026-10-02 | Wire analysis found the slot rule (redacted 16-byte span followed by the record's length-prefixed display name) and that other players' UUIDs are in clear text. |
| 2026-10-02 | `fill_local_player_uuid` implemented; 8 unit tests + capture-fixture assertions; 1 span in each of 25 bundles, 0 in the interest=91 and other-player bundles. |
| 2026-10-02 | **VERIFIED LIVE** PID 25952 / session 232: `writerStatus1` 0→2, `managerSetContext` 0→2, manager `+0x08/+0x10` null→non-null, portrayal inserts 148→226. The world renders with the player in it. Evidence `research/sessions/world_20261002T065937Z_pid25952_session232/`. |

## Blocked by this feature

Movement, inventory and instances: all need a possessed player first. They are
now unblocked and are the current frontier.
