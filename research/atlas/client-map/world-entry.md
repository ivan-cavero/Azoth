# World entry — REP connection, V3 registration, spawn ladder

Build analyzed: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` ·
Status: **solved and reproducible** as of 2026-10-07 (see
`../../docs/PRIVATE-CLIENT-RUNBOOK.md`).

Historical note: the older Gate 7 interpretation below attributed the red cable
to missing `AZOTH_REPLAY_INPUT_RESPONSE` traffic. Direct icon/ALC measurements
in `client-functions.json` supersede that interpretation: input responses do not
clear the red ALC/HUD warning. REP transport, ALC/HUD state, and movement are
separate acceptance gates; see [`../../STATUS.md`](../../STATUS.md).

## Overview

1. DTLS handshake to `RepAddress` from the queue ticket.
2. `RegistrationRequestV3Msg` -> `RegistrationResponseMsg` (`rep.ready` 0->1).
3. Post-V3 spawn ladder: SelfIdent, LevelInfoChanged, replica creation, spawn.

Wire detail is maintained in `../../docs/REP-PROTOCOL.md` (Carrier envelope,
MessageRecord flags, V3 layouts); this file records flow knowledge and the
spawn ladder as it is confirmed. Do not duplicate byte layouts here.

## Confirmed ladder (measured 2026-10-07, `Game.log`)

```
StartREPConnection            "start REP connection RepAddress = 127.0.0.1:9000, worldId = …"
WaitingForREPConnection       "REP socket connection established"
                              "received registration response from REP"
WaitingForActorGameConnection "actor game connection succeeds"
WaitingForSpawnPoint          "spawn point found"
WaitingForPlayerSpawn         LevelInfoChanged; map load starts
InGame                        "player spawn succeeds, in game"
```

The world-entry setting required for this ladder to end in a rendered world is:

- `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` — without it the context lives and
  the map loads but the screen stays black (gate 6).

`AZOTH_REPLAY_INPUT_RESPONSE=1` replays captured typed responses, but it is not
a fix for the current red ALC/HUD warning and is not proof of a usable/stable
client connection. Do not label it Gate 7 completion.

A client-side disk patch is required for the DTLS pin (gate 4).

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| Loading screen | post-selection | waits for spawn ladder | REP messages | STATUS.md confirmed list |

## Client state machine

- The ladder is now **observed end to end** on this build (see the confirmed
  ladder above), not imported from the 1.365 map.
- The black screen was **not** a ladder defect: it was the ClientContext
  predicate (`Initialize()` -> `Cleanup()`), fixed client-side, plus the
  possession setting (gate 6). See `../../docs/PRIVATE-CLIENT-RUNBOOK.md`.
- `open:` movement authority is a separate, in-world problem
  (`in-world.md`), not a world-entry one.

## Messages and payloads

- Registration V3 request/response: exact layouts in
  `../../docs/REP-PROTOCOL.md` (validated against a real capture).
- CONNECT/ACK system messages: known ids in REP-PROTOCOL; **the CONNECT_ACK
  shape we send is NOT accepted** — open defect with candidate causes listed
  there. `open:` decompile the client CONNECT_ACK handler (cookie compare) to
  settle it.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| game_connection_stream_processor_slot (confirmed) | 0x146425cb0 | inbound stream | GameConnection stream handling | client-functions.json |
| javelin_stream_processor (confirmed) | 0x146b69ad0 | datagram stream | record decode | client-functions.json |
| javelin_inbound_decode_entry (confirmed) | 0x146b6eb70 | decoded record | type dispatch | client-functions.json |
| javelin_inbound_type_dispatch (confirmed) | 0x146b6f190 | typed payload | handler routing | client-functions.json |
| state_record_bundle_parser (confirmed) | 0x146af20d0 | state bundle | state apply | client-functions.json |
| load_context_and_level (candidate) | 0x146448cd0 | predicate flag | `ClientContext::Initialize` | `campaign/world-entry/` |
| replication_unreliable_gate (candidate) | 0x14643e7b0 | `clientContextInstanceId` | accepts/​rejects unreliable replication | `campaign/world-entry/` |

## Framework reference (external, different wire generation)

- The client's REP stack is **GridMate** (Carrier/Replica/DataSet/RMI).
  GridMate was **removed from O3DE in 2022 (PR #9026)** — the reference source
  lives in O3DE git history / Lumberyard 1.x, NOT the current O3DE docs.
- Current O3DE Multiplayer Gem/AzNetworking docs describe a different
  (delta-replication) model; useful for concepts (authority roles, ACK
  vectors), wrong for wire layout. Do not use it to justify a Javelin wire
  claim.

## Data and assets

- `lc_spawnslice_console_command` (confirmed, 0x14101b4b0) — dev command that
  can force a spawn slice load; hidden/dev surface worth documenting fully.

## Open questions

- `open:` exact message(s) that flip ladder 13->14 (candidate: GridMate
  NewProxy carrying the player actor).
- `open:` what the client waits for before/after component creation for the
  local player (physics components missing — STATUS.md).

## Negative findings

- Replaying the old 1.365 state bundle does not advance the current ladder.
- Input/focus delivery are NOT the movement blocker (verified).
- The DTLS trust-patch applied with Frida during startup mapping crashes the
  client; use the disk patch (`PRIVATE-CLIENT-RUNBOOK.md`, gate 4).
- Applying the world-phase memory patches during load hangs the client; apply
  them at character select.
