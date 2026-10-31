# In-world — movement/physics, interaction, replication, zoning

Build analyzed: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` ·
Status: current as of 2026-10-07 (world renders, player possessed, session
stable; movement still open).

## Overview

1. Player entity fully spawned (end of the world-entry ladder).
2. **Session stability** — solved (gate 7).
3. **Movement authority** — open; needs a server→client channel-1/2 reply.
4. Interaction (E key etc.), inventory/menus, zoning transitions — not yet
   exercised.

## What a good session looks like (measured 2026-10-07)

With the full runbook sequence (`PRIVATE-CLIENT-RUNBOOK.md`) plus
`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` and `AZOTH_REPLAY_INPUT_RESPONSE=1`:

- `[ClientContext] Initialize()` with **no** following `Cleanup()`.
- `GameConnectionWrapper: player spawn succeeds, in game` → `InGame`.
- `[GDERenderManager] Init()`; physics active.
- The world renders (`NewWorld_VitaeEterna`): town, NPCs, third-person camera
  on the character, HUD, quest tracker, minimap, chat.
- 13+ minutes with **0** `OnLocalNetworkConnectionWarning`, **0**
  `State(InGame) is timeout`, **0** `OnConnectionFail`.

## Warnings and errors in a clean session (exhaustive)

These are every `[WARNING]`/`[ERROR]` line in a clean session. Each one is a
server-side gap, a benign physics note, or a client double-init.

| Count | Line | Layer | Assessment |
| --- | --- | --- | --- |
| 26 | `[WARNING] Slice: Couldn't get Transform component on the slice!` | entity/component | Entities instantiated from `slices/remoteplayer.dynamicslice` have **0 components**; the transform lookup fails. The local player is unaffected. Server-side data gap. |
| 25 | `[ERROR] RMIDispatch: The facet target ID couldn't be found when trying to dispatch the RMI message.` | dispatch | `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems` targets a facet that does not exist locally. Server-side: the server sends an RMI for a facet the client has not created. |
| 1 | `[WARNING] SocialComponentClientFacet::RequestGetPlayer: Requesting player data for empty characterId` | identity | The client's character id is the placeholder `11111111-1111-1111-1111-111111111111`. Server-side: serve a real character UUID in `LoginInfoList.Characters`. |
| 1 | `[WARNING] Physics: Sphere shape has non-uniform scale [0.630,0.630,0.585]~. Origin is Invisible Collision & Selection (Sphere)` | physics | Benign; a shipped asset. Not actionable. |
| 1 | `[ERROR] XDllSingleton: Singleton already instantiated!` | engine | A module registers a singleton twice. Benign for gameplay; worth a note only if a subsystem misbehaves. |

Confirmed with the same session's `Game.log` (2026-10-07 21:20–21:46).

### Why the two big ones are inherent to replaying a capture

Both the 26 Slice warnings and the 25 RMIDispatch errors come from the
**replayed capture**, not from our server logic:

- The capture is a snapshot of **someone else's session**. It contains RMI
  messages and slice instantiations for entities/facets that belonged to that
  session (other characters, storage components). Our replay forwards those
  bodies verbatim, so the client is asked to dispatch to facets it never
  created. A hand-built server that only sends the local player's own state
  would not produce them.
- The `remoteplayer.dynamicslice` entities with 0 components come from the same
  snapshot: the capture's remote players were captured mid-load.

So these are **expected artifacts of a capture-driven replay**, not defects in
the Azoth server, and they disappear once the server constructs its own world
state instead of replaying a recording. Do not spend a game restart trying to
"fix" them in the replay.

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
- **Re-measured 2026-10-07** (gate-6 session, `rep_traffic.jsonl`):

  | Direction | ch0 | ch1 | ch3 |
  | --- | --- | --- | --- |
  | client → server | 867 | **15688** | 16675 |
  | server → client | 1149 (+1892 ACK) | **0** | 16566 |

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

The local-player state stream (`0x635`, client→server, channel 1):

```
off 0x00   4 B   hash/seq (varies per message)
off 0x08  16 B   player entity UUID  1a954abc-4b31-85bf-be37-c3d8592618e0
off 0x18   4 B   typed header  00 01 b5 18
off 0x1c   ...   second GUID  518fbde4-b9a6-…
                 local-player key  …bf85314bbc4a951a
                 incrementing counter
```

Sizes in the capture: 93/108/123/138/153 (+15 B per message). Live sizes:
119/120. No clean position floats are visible in the body (the UUIDs and the
counter dominate), so the reply's field layout cannot be guessed from the
client→server form.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| cdk_typed_stream_reader (candidate) | 0x146b6eb70 | inbound typed records | per-type parse | `campaign/in-world/` |
| typed_message_dispatcher (candidate) | 0x146b6f190 | message GUID | refreshes the InGame activity clock on its miss path | `campaign/in-world/` |
| state_bundle_record_visitor (candidate) | 0x141717fc0 | `interestId`/`clientContextId` | actor build | `campaign/in-world/` |
| statebundle_record_header (candidate) | 0x146af20d0 | record body | record id + fragments | `campaign/in-world/` |
| ingame_activity_timer (candidate) | 0x146445e10 | per-state budget | forces disconnect at 10 frames | `campaign/in-world/` |
| local_player_context_manager_dispatch (candidate) | 0x146764cd0 | option-gate status | sets the manager context | `campaign/in-world/` |
| component_byname_create_hub (candidate) | 0x141416740 | component TYPE NAME | hashes the name and stores the factory | `campaign/in-world/` |
| rigidbody_component_setup (candidate) | 0x14095ec40 | descriptor {147f84b10} | calls the create hub | `campaign/in-world/` |
| player_component_client_facet_factory (candidate) | 0x14661dd30 | — | local-player facet construction | `campaign/in-world/` |

### The by-name component path (movement lead, updated 2026-10-07)

`FUN_141416740` is the **component create/register hub keyed by the component
TYPE NAME**: it computes an FNV-style hash of a name string and stores the
factory/callback in a container at `param_1+0x188` / `+0xf8` / `+0x2b8`. It is
reached by the RigidBody path (`FUN_14095ec40` -> `FUN_141416740` with the
descriptor `{147f84b10}` and factory `FUN_140c557e0`).

This is the function the earlier note (`component_byname_creation_never_runs_
20261005`) found at **0 calls** during the world-entry bursts. So the
"components come from the slice instantiator, not the by-name path" claim is
now anchored to a concrete function with a concrete caller — the physics
components would be created here if that path ever ran.

## Data and assets

- `slices/player.dynamicslice` — resolves the transform type
  `{484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0}` on an entity with 124 components.
- `slices/remoteplayer.dynamicslice` — the 0-component entities behind the 26
  transform warnings.

## Open questions

- `open:` **the channel-1/2 reply the client expects.** The movement message
  family is now known by name and GUID (see below); the missing piece is the
  **field layout** of `StartMovementCommunicationMsg` /
  `ReceivePlayerPositionClientMsg` and which one the server sends first.
  Decompile the client's inbound handlers for those GUIDs.
- `open:` whether the local player needs a character-controller/physics
  component that only server replication creates.
- `open:` why `RequestGetPlayer` sees an empty character id, and whether a real
  UUID in the login-info list fixes it.
- `open:` interaction, inventory, and zoning - not yet observed.

## The movement message family (found 2026-10-08)

The client ships a complete named movement message family. Full GUID registry in
[`../../docs/JAVELIN-MESSAGE-GUIDS.md`](../../docs/JAVELIN-MESSAGE-GUIDS.md).

| Type | GUID |
| --- | --- |
| `StartMovementCommunicationMsg` | `767fc9bf-1c8d-417f-ad19-c51e363d4df0` |
| `ReceivePlayerPositionClientMsg` | `39ca8bca-2ee8-4104-b0e9-7c2a51b52fb4` |
| `AckMovementMsg` | `5ad005ae-375c-4f2d-a00e-3ff9f6f01069` |
| `CommitMovementMsg` | `78ec38b5-d408-4f06-8aaf-60e7fda45cee` |
| `CheckMovementStatusMsg` | `44ba8334-c3aa-476e-855c-27364bf8a964` |
| `CancelMovementMsg` | `a9da71b4-4dcf-46e6-afa2-dbbe9e5ced0e` |
| `AbortMovementMsg` | `adaa28e6-b831-4505-8f05-fe32e000bd5d` |
| `MovementTimeoutMsg` | `4604a3cc-2cac-4a93-a0e2-d330041777e6` |
| `ProcessDeferredMovementRequestsMsg` | `4c220b64-c728-4d31-9c1e-6244e8089215` |
| `MoveActorMsg`, `MoveActorToHubMsg`, `MoveAnActorMsg` | `5570cfb7-…`, `0a8f6818-…`, `4d1e559d-…` |

This is the target list for the movement reply: the server drives the client
through this family (`StartMovementCommunicationMsg` -> position updates ->
`AckMovementMsg`/`CommitMovementMsg`) and the client already has the handlers.

## Why the `0x15d` heartbeat never stopped the timeout (mechanism, 2026-10-08)

The typed dispatcher `FUN_146b6f190` compares each inbound message's type GUID
(via `FUN_146158ba0`) against a fixed set of singleton type descriptors. A
message whose type is IN that set takes the "hit" path and does **not** refresh
the InGame activity clock; a type NOT in the set takes the "miss" path and
does. Confirmed members include `PingMsg`
(`85c7e01e-55de-4a6e-afc5-80fa9a8ad260`), `TimeSynchMsg`,
`RegistrationResponseMsg`, `ClientAddEntryMsg`.

`PingMsg` being a singleton is exactly why the `0x15d` heartbeat could run
forever without clearing `State(InGame) is timeout`, while the `0x1096`/`0x1097`
replies (not singletons) did clear it. See `SERVER-CONTRACT.md`.

## Negative findings

- A dedicated reply to the channel-1 `0x635` is not a proven cause of the
  transform-spawner null; the official capture has no 1:1 reply to `0x635`.
- Looping the captured `0x08` tail (`STATE_STREAM`) re-triggers the login/spawn
  path and costs the ClientContext — it is OFF by default and must not be
  re-enabled as a fix.
- Re-sending `0x1096`/`0x1097` (`INPUT_RESPONSE`) fixes the cable and the
  timeout but does **not** move the player; they ride channel 0.
- The `0x635` body carries no clean position floats, so the reply cannot be
  derived by analogy from the client→server form.
- Echoing the client's channel-1 record back on channel 1
  (`AZOTH_REPLAY_CHANNEL1_ECHO=1`) does not move the player and re-introduces
  `State(InGame) is timeout`. See `SERVER-CONTRACT.md` negative results.
- A server→client channel-1 reply is still the leading hypothesis, but it must
  carry the correct type and fields, not just any channel-1 traffic.
