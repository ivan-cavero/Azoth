# In-world — movement/physics, interaction, replication, zoning

Build analyzed: pending · Status: open

## Overview

1. Player entity fully spawned (end of world-entry ladder).
2. Movement input -> physics authority question.
3. Interaction (E key etc.), inventory/menus, zoning transitions.

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| (pending) | | | | |

## Client state machine

- `open:` movement authority model — which local components must exist before
  the client simulates movement, and what the server must acknowledge.
- **Reframed 2026-10-05** (`movement_replication_asymmetry_20261005` in
  `../client-functions.json`): the client/server exchange is asymmetric on the
  player-state channel. The client broadcasts its local-player state on
  channel 1 (type 0x635, ~31.8k records in one session); the server answers
  ONLY on channel 0 (replay + activity stream) and channel 3 — zero channel-1
  and channel-2 traffic in either direction back. The replay capture itself
  contains no ongoing server→client player replication, so the reply stream
  must be **constructed server-side**, not replayed.
- Measured the same session (`component_byname_creation_never_runs_
  20261005`): the client never attempts by-name component creation, the
  component cluster, or the transform spawners during world entry — those
  paths are dead in this flow; player components come from the slice
  instantiator. The missing physics is therefore upstream of component
  creation: the server must produce the player-state replication first.
- Earlier framing (local entity lacks rigid-body/character-physics
  components) still holds; `physics_component_guids_corrected_20261005`
  supersedes the 2026-10-04 GUID list — read the correction before hooking
  by type id.

## Messages and payloads

- REP data channels / chunk updates carry component state; envelope and
  record framing in `../../docs/REP-PROTOCOL.md`. Per-component schemas go in
  `../models.json` as they are observed.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| local_player_actor_prototype_builder (confirmed) | 0x1416957c0 (8654f01d…) | spawn request | local player entity | client-functions.json |
| local_player_context_manager_dispatch (confirmed) | 0x146764cd0 | context events | local player context | client-functions.json |
| replica_portrayal_update (confirmed) | 0x14178db00 | portrayal data | replica update | client-functions.json |
| replica_rmi_target_lookup (confirmed) | 0x1416bcba0 | RMI target id | remote call delivery | client-functions.json |
| netbinding_component_creators (confirmed) | 0x14628bea0 | net binding | component creation | client-functions.json |
| transform_spawner_chain_confirmed_20261005 (confirmed) | 0x141763b70 | spawn slice | transform spawner chain | client-functions.json |
| gametransform_entity_attach (confirmed) | 0x145c79e80 | entity + transform | attach | client-functions.json |
| replication_unreliable_gate_20261003 (confirmed) | 0x14643e7b0 | gate state | unreliable replication | client-functions.json |
| component_cluster_table_driven (confirmed) | 0x141761dd0 | cluster table | component batch creation | client-functions.json |

## Data and assets

- `player.dynamicslice` contents checked — no physics components (STATUS.md).
- `open:` which slice/PAK data defines the local player component set at
  spawn (`dynamicslice_path_suffix_check`, `slice_transform_lookup`).

## Open questions

- `open:` full component set the client requires on the local player entity
  before movement simulates, and which message creates each.
- `open:` interaction (use/loot) message chain.
- `open:` zoning/region transition handshake.
- `open:` the channel-1/2 server→client reply to the client's 0x635
  player-state stream: exact type ids, cadence, and payload schema. The
  capture has one short exchange (0x1096/0x1097 right after the 0x635 burst,
  replay seq 0x75/0x76); `AZOTH_REPLAY_INPUT_RESPONSE=1` re-sends those two
  bodies verbatim as an A/B lever for the "Time since last response" HUD.

## Negative findings

- Input/focus delivery verified working — not the blocker.
- Client self-reconnect kills the local context (`client_self_reconnect_
  kills_context_20261004` in `../client-functions.json`).
