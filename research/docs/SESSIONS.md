# Captured sessions

All on this PC, 2026-09-06, cluster `fra-prod`, world `live-1-12-2` / `86ae8332-ed32-420e-985c-61011022847a`, Omni persona `amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c`. Raw (`Game.log.raw`, pcap) is **not versioned**.

## `live_20260906_155045` — existing character

- ~291 s, InGame True, player **xNozus**, character `07631b31-78f5-419d-8be8-ddca69eecbc9`
- REP `35.71.153.244:23771` (or `58257` in an earlier log from the same day)
- pcap ~24k packets (pktmon non-Ethernet frames; the analyzer already decodes SNAP/IPv4)
- Full ladder up to InGame

## `live_20260906_160330` — create + FTUE + switch

- ~725 s, 1266 Game.log lines, 429 events, 58195 packets
- **Two logins in the same session** (identities.json only saved the last one; the timeline is in fixtures):

| | New | Old |
| --- | --- | --- |
| Name | Nozusss | xNozus |
| Character | `abdbd9e8-50f8-4c05-a41b-3f17e9b0407e` | `07631b31-78f5-419d-8be8-ddca69eecbc9` |
| REP | `52.223.18.203:48274` | `52.223.18.203:33000` |
| InGame | 14:07:03 | 14:14:16 |

Maps: `NW_Frontend_NightHaven` → `FTUE_V2_CC` (creator) → `FTUE_V2` (SoleSurvivor tutorial) → `NewWorld_VitaeEterna` → frontend → back into Aeternum with xNozus.

`WaitingForPlayerSpawn` **was not a hang**: it is the state when changing maps (`InGame → WaitingForPlayerSpawn` ~4 s) and the `from` of the last STATUS.txt transition (`to: InGame`).

CMS 62 events, Vivox 91. RMIs seen: GlobalStorage, Gatherable Interrupted, EventNotification, GridTracking phasing, GameMode queue.

## `live_20260906_173554` — combat / gather / death (xNozus)

- ~881 s, 1363 lines, 635 events, **118643** packets, InGame True, `current_state InGame`
- Same toon `xNozus` / `07631b31-…`, same world, new REP `35.71.153.244:38811`
- Single `WaitingForPlayerSpawn → InGame` on entry (15:37:29). **Dying and respawning does not change GameConnection** (stays InGame).
- Combat (log): `CameraLockComponentClientFacet` ×6 (target lock, 15:39–15:40); `SlayerScriptComponent` unknown-entity CRC (15:44:46, skills).
- Gather: `GatheringInterrupted` ×9, **7 distinct nodes** (15:44:53–15:48:59). Completing a gather is not logged; only the interrupt when the node disappears.
- Inventory/equip: **zero lines**. It goes over DTLS (pcap ~69k records / 20 MB to the REP).
- Other players: `slices/remoteplayer.dynamicslice` (AOI). `SocialComponentClientFacet::RequestGetPlayer` with empty `characterId` (15:43:14) — group/expedition UI with no people.
- Dungeon: no `LevelInfoChanged` to `nw_dungeon_*`, no second REP. `OnLeftQueueForGameModeMsg` is spawn noise, not a real queue.
- Death: `entity was destroyed` notices + `DetectableComponent` rigid body physics; **no Death/Respawn string**.
- Vivox 406 events (3D grids while walking). Noise, not combat protocol.

## What the kit still can't see

HTTPS bodies (TLS official) and DTLS plaintext. Combat/inventory/death **live in DTLS**, not in Game.log. The mock will see them once the client talks to Azoth. Dungeon still pending (needs a group or a solo instance).
