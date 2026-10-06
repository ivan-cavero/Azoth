# World entry — REP connection, V3 registration, spawn ladder

Build analyzed: pending · Status: open (wire layer partially known)

## Overview

1. DTLS handshake to `RepAddress` from the queue ticket.
2. `RegistrationRequestV3Msg` -> `RegistrationResponseMsg` (`rep.ready` 0->1).
3. Post-V3 spawn ladder, states 10->14 (SelfIdent, LevelInfoChanged, replica
   creation).

Wire detail is maintained in `../../docs/REP-PROTOCOL.md` (Carrier envelope,
MessageRecord flags, V3 layouts); this file records flow knowledge and the
spawn ladder as it is confirmed. Do not duplicate byte layouts here.

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| Loading screen | post-selection | waits for spawn ladder | REP messages | STATUS.md confirmed list |

## Client state machine

- Ladder 10->14 from the external 1.365 map is **statically-derived for a
  different build** — `open:` verify each transition on ours before
  implementing (see `../../docs/REP-PROTOCOL.md` "Post-V3 state ladder").
- Known blocker (STATUS.md): local player entity is created but never gets
  rigid-body/character-physics components; the `GameTransformComponent`
  creation path was not reached in the last replay.

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
| game_connection_stream_processor_slot (confirmed) | 0x146425cb0 (8654f01d…) | inbound stream | GameConnection stream handling | client-functions.json |
| javelin_stream_processor (confirmed) | 0x146b69ad0 | datagram stream | record decode | client-functions.json |
| javelin_inbound_decode_entry (confirmed) | 0x146b6eb70 | decoded record | type dispatch | client-functions.json |
| javelin_inbound_type_dispatch (confirmed) | 0x146b6f190 | typed payload | handler routing | client-functions.json |
| state_record_bundle_parser (confirmed) | 0x146af20d0 | state bundle | state apply | client-functions.json |

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

- Replaying the old 1.365 state bundle does not advance the current ladder
  (STATUS.md confirmed list).
- Input/focus delivery are NOT the movement blocker (verified).
