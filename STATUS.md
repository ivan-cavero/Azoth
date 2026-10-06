# Live status

Updated: 2026-10-06. Exact function evidence is in
[`research/atlas/client-functions.json`](research/atlas/client-functions.json);
the consolidated wire reference is
[`research/docs/JAVELIN-PROTOCOL.md`](research/docs/JAVELIN-PROTOCOL.md).

## Active objective

Make the local player move in the private client. Entry to the world is
solved and reproducible; movement is the only open failure.

## Confirmed

- Gateway and world server connect; the client loads Monarch's Bluffs and
  possesses the local player. Clean sessions show 1 skipped bundle, 0
  disconnects, 0 transport errors, 0 warnings — the server is stable.
- Input delivery is verified: keys, mouse look, and UI actions reach the game.
  Focus was a harness bug, now fixed (`scripts/focus-window.py` verifies
  foreground). WASD still does not move the player (motion ratio 0.13x).
- **Movement blocker, measured 2026-10-05** (`movement_replication_
  asymmetry_20261005`): the client broadcasts its local-player state on
  channel 1 (type 0x635); the server never answers on channel 1/2. The reply
  stream must be constructed server-side — the capture does not contain it.
- The client never attempts by-name component creation, the cluster, or the
  transform spawners during world entry; player components come from the
  slice instantiator (`component_byname_creation_never_runs_20261005`).
- `player.dynamicslice` has no physics components; the 2026-10-04 physics
  GUIDs were wrong — use `physics_component_guids_corrected_20261005`.
- Debug cameras ship in the client: `change_camera`=O verified live;
  `debug_camera` free-fly (WASD+Space) is disabled by `enable="0"` and can be
  enabled with a PAK edit — see `research/atlas/levers.md`.

## Next useful step

Design the server-side channel-1/2 reply to the client's 0x635 player-state
stream (protocol-analysis prompt), using the single short captured exchange
(0x1096/0x1097) and the consolidated message registry in JAVELIN-PROTOCOL.md
as the starting contract. A/B levers that already exist:
`AZOTH_REPLAY_INPUT_RESPONSE=1`, the debug-camera PAK edit. Do not return to
input/focus checks or connection stability — those are solved.

## Project structure

The game profile/runtime, PAK index, tools, and old logs live in ignored
project-local paths (`private-client/`, `.azoth/`, `reverse/builds/`). The
project restructure (single `az.py` entry point, phase campaign, client map,
agent prompts) is complete on this branch pending merge to main.
