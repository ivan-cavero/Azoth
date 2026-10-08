# Live status

Updated: 2026-10-07 (overnight session). Exact function evidence is in
[`research/atlas/client-functions.json`](research/atlas/client-functions.json);
the consolidated wire reference is
[`research/docs/JAVELIN-PROTOCOL.md`](research/docs/JAVELIN-PROTOCOL.md); what the
client expects from the server, phase by phase, is
[`research/docs/SERVER-CONTRACT.md`](research/docs/SERVER-CONTRACT.md); how to
bring up and patch a private run is
[`research/docs/PRIVATE-CLIENT-RUNBOOK.md`](research/docs/PRIVATE-CLIENT-RUNBOOK.md).

## Active objective

Make the local player move in the private client. **Entry to the world, the
rendered world, the possessed player, and a stable session are all solved and
reproducible.** Movement is the only open failure.

## Confirmed

- **The private run works end to end (2026-10-07).** With the runbook sequence
  the world renders and the player is possessed: `Initialize()` without
  `Cleanup()`, `player spawn succeeds, in game`, `InGame`, physics active.
  Screen: Everfall/Brimstone Sands with NPCs, third-person camera on the
  character, HUD, quest tracker, minimap, chat.
- **The session is stable.** The recommended configuration
  (`AZOTH_REPLAY_INPUT_RESPONSE=1`, `AZOTH_CHUNK_GAP_MS=20`) held **InGame for 20
  minutes** validated on 2026-10-08: server steady at 21 app-data/s + 25
  outbound/s, **0** resends, **0** `transportError`, **0**
  `OnLocalNetworkConnectionWarning`, **0** `State(InGame) is timeout`, then a
  clean disconnect. Without the pacing, a burst can starve the client and it
  drops the transport ~16 s after spawn (gate 8).
- **Private-run gates 1-8** (see the runbook). Three of them fail silently:
  Caddy CA trust, the DTLS pin, and the server settings below.
  - Gate 5 (black screen) = the ClientContext predicate; fix
    `patch-predicate-flag.py` at character select.
  - Gate 6 (no player) = server env `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`.
  - Gate 7 (red cable/timeout) = server env `AZOTH_REPLAY_INPUT_RESPONSE=1`.
  - Gate 8 (post-spawn transport drop) = pace the replay:
    `AZOTH_CHUNK_GAP_MS=20`. Root cause: the burst (~91 chunks/s) starves the
    client's network thread; a healthy run paces at ~21/s.
- **Warnings in a clean session are now enumerable and few** (see
  `atlas/client-map/in-world.md`): 26 × Slice transform (0-component
  remoteplayer slices), 25 × RMIDispatch facet-not-found
  (`GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`), 1 ×
  `RequestGetPlayer: empty characterId`, 1 × benign physics sphere note, 1 ×
  `XDllSingleton already instantiated`. All are server-side data gaps or
  benign.
- **The character id is a placeholder.** The client sends and logs
  `11111111-1111-1111-1111-111111111111`. Serving a real UUID in
  `LoginInfoList.Characters` may replace it.
- Input delivery is verified (scan-code SendInput reaches the client; the
  camera rotates with mouse look). WASD still does not move the player.
- The client never attempts by-name component creation, the cluster, or the
  transform spawners during world entry; player components come from the slice
  instantiator.

### Movement blocker (re-measured 2026-10-07, target list found 2026-10-08)

The client broadcasts its local-player state on **channel 1** (type `0x635`)
and the server answers **only** on channel 0 and channel 3:

| Direction | ch0 | ch1 | ch3 |
| --- | --- | --- | --- |
| client -> server | 867 | **15688** | 16675 |
| server -> client | 1149 (+1892 ACK) | **0** | 16566 |

The capture contains no 1:1 server reply to `0x635`; its only candidates
(`0x1096`/`0x1097`) ride channel 0 and fix stability, not movement. The reply
must be **constructed server-side**.

**The next step is now concrete.** The client ships a complete named movement
message family with AZ type GUIDs: `StartMovementCommunicationMsg`,
`ReceivePlayerPositionClientMsg`, `AckMovementMsg`, `CommitMovementMsg`,
`CheckMovementStatusMsg`, `CancelMovementMsg`, `AbortMovementMsg`,
`MovementTimeoutMsg`, `ProcessDeferredMovementRequestsMsg`, `MoveActorMsg`,
`MoveActorToHubMsg`, `MoveAnActorMsg`. Full registry (156 types) in
`research/docs/JAVELIN-MESSAGE-GUIDS.md`. The client already has the handlers;
the server must drive the family, and the field layouts come from decompiling
those handlers.

**Gate 7 mechanism explained (2026-10-08).** The typed dispatcher
`FUN_146b6f190` compares each inbound type GUID against a singleton set. A hit
does NOT refresh the InGame activity clock; a miss DOES. `PingMsg` is a
singleton, which is why the `0x15d` heartbeat never cleared the timeout while
`0x1096`/`0x1097` did.

## Decompilation campaign

**108** targets across the six player-visible phases (launch 15, login 14,
server-select 11, character-select 2, world-entry 15, in-world 51), up from 53
at the start of the session. Manifest:
`research/atlas/decomp-campaign.json`; per-build state and `.c` output under
the ignored `reverse/builds/<sha256>/campaign/`. The bulk corpus remains
complete (423,579 `.pdata` functions).

## Next useful step

**Movement, with the target list now in hand.** The client ships a complete
named movement message family (16+ types with AZ GUIDs, including
`StartMovementCommunicationMsg`, `ReceivePlayerPositionClientMsg`,
`AckMovementMsg`, `CommitMovementMsg`) — the registry is in
`research/docs/JAVELIN-MESSAGE-GUIDS.md`. The server drives the client through
that family; the missing piece is the field layout, which comes from
decompiling the client's inbound handlers for those GUIDs. Everything else
(world entry, possession, stability) is solved.

Also ready, in priority order:

1. Wire the movement family into the world server's reply path.
2. The three server-side warning gaps: serve a real character UUID; stop
   sending RMIs for facets the client lacks; check the 0-component
   remoteplayer slices (all are capture-replay artifacts — see the runbook).
3. Merge the restructure branch to main.

Do not return to input/focus checks, connection stability, or gates 1-8 — all
solved and documented in `research/docs/PRIVATE-CLIENT-RUNBOOK.md`.

## Project structure

The game profile/runtime, PAK index, tools, and old logs live in ignored
project-local paths (`private-client/`, `.azoth/`, `reverse/builds/`). The
project restructure (single `az.py` entry point, phase campaign, client map,
agent prompts) is complete on this branch pending merge to main.
