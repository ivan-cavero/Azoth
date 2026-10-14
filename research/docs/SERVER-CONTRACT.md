# Server contract — everything the client expects, phase by phase

This is the actionable companion to [JAVELIN-PROTOCOL.md](JAVELIN-PROTOCOL.md)
(wire format) and [CLIENT_CONTRACT.md](CLIENT_CONTRACT.md) (HTTP shapes). It
answers one question: **for each phase, what must the server provide, and is it
implemented?** Status is measured against the private client on build
`8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`.

Legend: **done** = the client accepts it and advances; **partial** = it advances
but something downstream is missing; **missing** = the client stalls.

## Phase map (measured state machine)

`GameConnection` state transitions observed in a clean private run
(`Game.log`, 2026-10-07):

```
Disconnected
 → QueryGameUpdateCheck          "no game update check needed"
 → QueueGameLogin
 → WaitingForQueuedLogin         HTTP POST /prod/game/login/queue/v2/jwt/omni
 → QueryForRemoteConfigClass  ⇄  WaitingForRemoteConfigClass   (4 rounds)
 → ObtainREPRequirements
 → StartREPConnection            "REP Address: 127.0.0.1:9000"
 → WaitingForREPConnection       DTLS + RegistrationResponse (V3)
 → WaitingForActorGameConnection "actor game connection succeeds"
 → WaitingForSpawnPoint          "spawn point found"
 → WaitingForPlayerSpawn         LevelInfoChanged, map loads
 → InGame                        "player spawn succeeds, in game"
```

Each arrow is a server obligation. The table below lists them.

## Phase 1 — Launch and title gate

| Obligation | Transport | Status |
| --- | --- | --- |
| Serve the channel document | `GET https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.json` | **done** |
| Serve CMS news/tiles/MOTD | `GET /newsstories/…`, `/marketingtiles/…`, `/motd/worlds_…` | **done** (ETag mandatory) |
| Serve content images | `GET client.content-service.amazongames.com/images/…` | **done** |
| Windows must trust Caddy's CA | — | **done** (`scripts/trust-caddy-ca.py`) |

The title gate ("press any button") is client-side; it needs no server call, but
it will not appear if the channel document fails (gate 2 in the runbook).

**Settings are entirely client-side.** The `OptionsDataBus` component
(`FUN_1445a7470`) owns `InitializeSerializedOptions`, `SerializeOptions`,
`SaveJson`, `LoadJson`, and the legal/help link handlers; values persist to
`@savedata@/usersettings_<hash>.javsave`. The server never sees them. See
`../atlas/client-map/launch.md` "Settings / options". The only server-visible
effect is the character UUID the option store feeds to the login queue.

## Phase 2 — Login

| Obligation | Transport | Status |
| --- | --- | --- |
| Platform tokens | `POST /games/new-world/tokens`, `POST /auth/platform/user/code` | **done** |
| AWS credentials | `GET /prod/credentials/omni` | **done** (STS-shaped, refreshed every 5 min) |
| Login info (persona, characters) | `GET /prod/game/getlogininfo/jwt/omni?channelId=…&includeNames=true&isTrialOwner=false` | **done** (dual-schema: camelCase + `LoginInfoList`) |
| Entitlements | `GET|POST /players/amzn1.developerPersonaId.…/games/new-world/platforms/steam/entitlements[/sync]` | **done** |
| World list | `GET /prod/game/worlds/list/jwt/omni` | **done** |
| Login queue ticket | `POST /prod/game/login/queue/v2/jwt/omni?channelId=…&tokenVersion=10` then refresh `…/queue/v2/{id}/jwt/omni` | **done** |

The ticket envelope is `LoginQueueResponse` with PascalCase fields; the parser
reads it through `FUN_14643d110`. `Signature` must be non-empty — the handoff
gate `FUN_14114b200` compares that string and an empty one never advances.
`RepAddress` in the ticket is what points the client at the world server.

Client functions: `getlogininfo_request_builder` (0x1474ea680),
`login_error_enum` (0x147fc3d08).

## Phase 3 — Server select

| Obligation | Transport | Status |
| --- | --- | --- |
| World list metadata | `GET /prod/game/worlds/list/jwt/omni` | **done** |
| Per-world config sets | `GET ags-javelin-remote-config.s3.amazonaws.com/applications/{public,publicGameplay}/configuration-sets/{ProductId,RegionId,CognitoId,WorldId}/…` | **done** |

The client queries the config sets for `ProductId`, `RegionId`, `CognitoId`, and
the selected `WorldId`, in both the `public` and `publicGameplay` applications,
for the `versionless` and `6031;6004151` variants. All are served.

## Phase 4 — Character select

| Obligation | Transport | Status |
| --- | --- | --- |
| Character list | `getlogininfo` `LoginInfoList.Characters` | **done** (seeded) |
| Character create/delete | `/characters`, `/characters/validator` | **not exercised** — the client makes 0 requests to these paths in every private run (measured 2026-10-07/08); the gateway route is a guessed shape kept as a fallback |

The screen renders because `LoginInfoList.Characters` has an entry. Empty seed
data leaves the panel blank (see `LESSONS.md` §4). To seed the panel, edit
`LoginInfoList.Characters`, not `/characters`.

## Phase 5 — World entry (REP)

| Obligation | Wire | Status |
| --- | --- | --- |
| DTLS handshake | DTLS 1.2, embedded `CN=New World` pin | **partial** (client-side disk patch required) |
| Carrier handshake | `SM_CONNECT_REQUEST` → CLOCK_SYNC + ACK flight | **done** |
| V3 registration | ch0 `>64 B` → 88 B `RegistrationResponseMsg` | **done** |
| Post-V3 flight | SelfIdent + LevelInfoChanged | **done** |
| Spawn ladder | captured `0x08` bundles | **done** |
| Local-player identity | `fill_local_player_uuid` rewrites 1 span/bundle | **done** (server env) |
| Level load | `0x663` LevelInfo, `NewWorld_VitaeEterna` | **done** |

## Phase 6 — In-world

| Obligation | Wire | Status |
| --- | --- | --- |
| Keep the session alive | `0x15d` heartbeat | **done** (on by default) |
| **Player movement authority** | ongoing `0x08` bundles carrying **record_id 1** | **done** — measured 2026-10-13 |
| Entity/actor replication | ongoing `0x08` bundles | **done** (`AZOTH_REPLAY_STATE_STREAM`, on by default) |
| Clear the ALC/HUD cable | the same record-1 bundles, re-sent faster than the amber threshold | **done** — measured 2026-10-13 |
| Answer the client's typed requests | see "Inbound requests" below | **missing** (43 request types, 0 answered) |
| Activity stream | `0x1b88` | **not needed** (the state stream clears the cable on its own) |

### Movement and the cable are the same record (RESOLVED 2026-10-13)

Both were "missing" for the same reason and neither needed a new message. The client only
simulates the local player while it is receiving that player's own AOI state, and the
authoritative position travels as **replicated state**, not as an RMI:

* the local player's own state is **`record_id 1`**, and in the capture it appears only in the
  four 7154-byte bundles at replay seq **0x98 / 0x9A / 0x9C / 0x9E** — all *below* the state
  stream's old default floor of `0xA0`, so the stream was re-sending every other entity's state
  and never the player's;
* the red cable is a client-side age of the ALC local client's `+0xAA8` stamp
  (`age = clock() - *(alc + 0xAA8)`; amber ~2 s, red ~15 s), and nothing we sent refreshed it
  except those record-1 bundles.

Measured, one variable (`AZOTH_REPLAY_STATE_STREAM=0` as the control):

| | stream ON | stream OFF |
| --- | --- | --- |
| W held 10 s | **moves** (WASD verified in all four directions; W/S 179.9 deg apart, A/D 178.5 deg, W/A 91.2 deg) | position frozen at `(9343.6416, 2786.7327, 87.538)` |
| HUD cable | **icon absent** | **RED** (red 3.7 %) |
| ALC stamp | refreshing, max age 100 ms | frozen, age growing to 262 s |

This supersedes the earlier reading in this file that movement needed "a constructed
server→client message on channel 1 (or 2)". It does not: it needs the captured record-1 state to
keep flowing, which the stream does by default. The `0x1096`/`0x1097` pair is delivered 828
times per session and does **not** clear the cable.

### Inbound requests: the client asks and we answer none

MEASURED 2026-10-14 with `scripts/inbound-inventory.py`. The full inventory, the classification
of every type, the unnamed ones and the request→response map live in
**[INBOUND-REQUESTS.md](INBOUND-REQUESTS.md)**; this is the summary.

In one session the client sent **37 distinct client→server types** (a longer session with more
UI paths exercises 43): **19 requests** (`*ComponentServerFacet_*`), **8 transport**, **1 input
stream**, **1 V3 re-registration**, **8 typed-but-unnamed**. The server has **no inbound typed
message dispatcher at all** (`grep -c dispatch_inbound` -> 0), so every request is acknowledged
at the transport level and then ignored. By channel: channel 1 = 8412 records and they are *all*
`ActionListComponentServerFacet_ReceiveInputFromClient` (wire 1589, the ALC input stream);
channel 0 = 543, of which 431 are `PingMsg`; channel 3 = 8891 Carrier/system records.

None of the requests currently produces a client-side complaint, which is why the gap was
invisible for so long. **Visibility fixed:** the server logs each distinct `(channel, type)`
once per session (`event: inbound-typed`) and, when the held responses are decided, one
`event: inbound-request-coverage` line splitting the client's types into `answerable_by_replay`
and `no_replay_response`.

The requests a playable world needs answered, in order:
`PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient` (2515),
`ObjectivesComponentServerFacet_UpdateTrackedObjectives` (1458) /
`..._SetObjectiveAutoPinning` (2709),
`ContractsComponentServerFacet_LookupContractsByParticipant` (2556) — the capture contains the
matching `0x08E6` response —,
`GlobalStorageComponentServerFacet_SetReplicateStorage` (387), and
`TimeComponentServerFacet_SyncToClient` (4248).

### Response scheduling: we answer only the questions the client actually asked

MEASURED 2026-10-13, CORRECTED 2026-10-14. The replay is **another client's capture**, so it
contains the server's answers to requests our client never makes. A clean session logged **29**
`RMIDispatch: The facet target ID couldn't be found` errors, all inside a single millisecond,
1 ms BEFORE `player spawn succeeds`, while the replay drains 8 s AFTER it.

The first fix classified each response by whether the client has the facet at all (a survey of
the live entity's bound facets) and dropped the absent ones. That was the right question asked
with the wrong instrument, and it was wrong in **both** directions:

| response | facet survey | request correlation | measured why |
| --- | --- | --- | --- |
| `0x1B88` GlobalStorage `ReceiveStorageSearchItems` (x23) | drop | **drop** | the client never sends `0x1B7F` |
| `0x0CA4` EventNotification `SyncNotifications` | drop | **drop** | unsolicited, facet absent — the only static drop left |
| `0x1067` VoiceChat `OnVoiceChatServiceRegistered` | drop | **send** | the client *does* send `0x066B` |
| `0x16A0` Inventories `OnQueryInventories` | *(sent unasked)* | **drop** | the client never sends `0x169D` |

The rule is now `rep.py::_deferred_decision`: a captured typed response is held until the
client's object graph exists, then sent only if the client sent the request it answers; a
response with no identifiable request is sent unless its facet was measured absent. The pairs
are derived from the capture's own ordering and from the family naming, and are verified by
`scripts/request-response-map.py --check`. Lever `AZOTH_REPLAY_REQUEST_GATING` (default on).

**Acceptance, measured: 29 -> 3 -> 1 dispatch error per session.** The remaining one is the
client's own `GridTrackingComponentClientFacet_UpdatePhasing`, and it is **not caused by the
scheduling policy**: it fires at spawn−1 ms while the message we send arrives 8 s later, and it
appears in every session measured, including one with the state stream off. It is a client-side
artifact of its own spawn sequence, bounded at one per session. (Note for the reader: the client
names that message in its `RMIDispatch` error, but the wire-name registry pairs the *name* with
wire 930, which the capture does not contain; the response we actually send is wire `0x1033`,
the only unnamed message in the capture at that point.)

## REP message registry (from the capture)

Directions: **R** = server→client (what we must send), **W** = client→server
(what we must understand).

### Server → client

| Type | Count | Sizes | Redacted | Notes |
| --- | --- | --- | --- | --- |
| `0x0008` | 79 | 78…427, + | yes | state bundles; the replication core |
| `0x1b88` | 23 | 42 | no | activity stream; 23 byte-identical copies |
| `0x015d` | 10 | 12 | no | heartbeat ping (client echoes 36 B) |
| `0x014f` | 4 | 12 | no | — |
| `0x18a6` | 4 | 40 | no | — |
| `0x00a4` | 2 | 20 | no | — |
| `0x0663` | 2 | 110 | no | LevelInfo (name + coatlicue path + floats + context key) |
| `0x16a0` | 2 | 153, 99819 | yes | item/collection state |
| `0x0003` | 1 | 88 | yes | registration/self-ident family |
| `0x040a` | 1 | 76 | no | — |
| `0x01be` | 1 | 76 | no | — |
| `0x065c` | 1 | 12706 | yes | large world-data blob |
| `0x0651` | 1 | 4 | no | — |
| `0x0ca4` | 1 | 102 | no | — |
| `0x136a` | 1 | 28 | no | — |
| `0x08e6` | 1 | 42 | no | — |
| `0x1033` | 1 | 498 | no | — |
| `0x1067` | 1 | 86 | no | — |
| `0x1096` | 1 | 80 | no | **player-state reply** (carries the local-player key) |
| `0x1097` | 1 | 24 | no | **player-state reply** (carries the local-player key) |

### Client → server

| Type | Count | Sizes | Notes |
| --- | --- | --- | --- |
| `0x015d` | 10 | 36 | heartbeat pong; echoes our tick |
| `0x0635` | 5 | 93…153 | **local-player state stream**; +15 B per message |
| `0x05b2` | 4 | 45, 93 | — |
| `0x1a59` | 3 | 45 | — |
| `0x0013` | 1 | 2750 | redacted; large client blob |
| `0x12f6` | 1 | 299 | redacted |
| `0x1098`, `0x09d3`, `0x09fc`, `0x0a95`, `0x10b0`, `0x101a`, `0x187c`, `0x187f`, `0x102e`, `0x102f`, `0x192c`, `0x101d`, `0x0f7f`, `0x066b`, `0x143d` | 1 each | 44…102 | typed requests, one per session |

## The `0x635` stream and the movement frontier
The client sends `0x635` on **channel 1** continuously once possessed. Layout
(measured from the capture, sizes 93/108/123/138/153):

```
off 0x00  4 B   hash/seq (varies per message)
off 0x04  ...   player entity UUID  1a954abc-4b31-85bf-be37-c3d8592618e0
                second GUID          518fbde4-b9a6-…
                local-player key     …bf85314bbc4a951a
                incrementing counter
```

Measured exchange in a live session (2026-10-07, `rep_traffic.jsonl`):

| Direction | Channel 0 | Channel 1 | Channel 3 |
| --- | --- | --- | --- |
| client → server | 867 | **15688** | 16675 |
| server → client | 1149 (+1892 ACKs) | **0** | 16566 |

The server answers on channel 0 and channel 3 but **never on channel 1**. The
capture contains no 1:1 server reply to `0x635` either: its only candidates are
the two `0x1096`/`0x1097` messages, which ride the typed stream (channel 0) and
carry the local-player key. Re-sending those (`AZOTH_REPLAY_INPUT_RESPONSE=1`)
removed the HUD cable and the `InGame` timeout but did **not** make the player
move.

**Superseded 2026-10-13.** Movement does NOT need a constructed channel-1 message. The
authoritative position travels as replicated state in the captured record-1 bundles, and the
client moves when those keep flowing (see "Movement and the cable are the same record" above).
The `0x635` stream is the client's INPUT direction and it was already working: the server
receives it at ~20 records/s and never needed to answer it on channel 1.

### The movement message family exists in the client (found 2026-10-08)

The client's executable contains a complete, named **movement** message family
with AZ type GUIDs (full registry in
[JAVELIN-MESSAGE-GUIDS.md](JAVELIN-MESSAGE-GUIDS.md), extracted from the static
type-descriptor region the typed dispatcher reads):

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
| `MoveActorMsg` / `MoveActorToHubMsg` / `MoveAnActorMsg` | `5570cfb7-…` / `0a8f6818-…` / `4d1e559d-…` |

This is the concrete target list for the movement reply: the server must drive
the client through this family (`StartMovementCommunicationMsg` -> position
updates -> `AckMovementMsg`/`CommitMovementMsg`), and the client already has the
handlers. Before this, the reply stream was described only as "channel 1/2";
now it has named types and GUIDs.

### Why the `0x15d` heartbeat never fixed the timeout (mechanism found)

The typed dispatcher `FUN_146b6f190` compares each inbound message's type GUID
(via `FUN_146158ba0`) against a fixed set of **singleton** type descriptors read
through accessors `FUN_1407f2e80`, `FUN_1407f6a30`, `FUN_1407f0940`,
`FUN_1407ebec0`, and seven more. The descriptors carry names, so the singleton
set is readable. Confirmed members:

| Accessor | Type | GUID |
| --- | --- | --- |
| `FUN_1407f2e80` | `RegistrationResponseMsg` | `104145a7-ff95-44f1-9468-21fb41c8ac2b` |
| `FUN_1407f6a30` | `TimeSynchMsg` | `038cd847-0653-4243-9a26-936e3bd7f312` |
| `FUN_1407f0940` | `PingMsg` | `85c7e01e-55de-4a6e-afc5-80fa9a8ad260` |
| `FUN_1407ebec0` | `ClientAddEntryMsg` | `e3578b38-69ad-4c13-a7dd-3fff752d98aa` |

A message whose type is IN this set takes the dispatcher's "hit" path and does
**not** refresh the InGame activity clock. A message whose type is NOT in the
set takes the "miss" path and **refreshes** the clock. `PingMsg` is in the set
— which is exactly why the `0x15d` heartbeat pings could run forever without
stopping `State(InGame) is timeout`, while the captured `0x1096`/`0x1097`
(not singletons) **did** stop it. This turns the gate-7 lever from an empirical
observation into an explained mechanism.

### Negative results (do not repeat)

- **Re-sending the captured `0x1096`/`0x1097`** (`AZOTH_REPLAY_INPUT_RESPONSE=1`)
  removes the cable and the timeout but does **not** move the player: those
  messages ride channel 0.
- **Echoing the client's own channel-1 record back on channel 1**
  (`AZOTH_REPLAY_CHANNEL1_ECHO=1`, an experimental lever added 2026-10-07) also
  does **not** move the player, and it **re-introduces** `State(InGame) is
  timeout` (5 within the first minutes of the run, versus 0 in the clean run).
  The client accepted the datagrams (no new warnings), but the echo is not a
  usable reply and is harmful. Default OFF. This rules out "the client just
  needs any channel-1 inbound traffic" and confirms the reply must carry the
  right type and fields.

## Implementation status summary

| Phase | HTTP | REP | Verdict |
| --- | --- | --- | --- |
| Launch | done | — | **works** |
| Login | done | — | **works** |
| Server select | done | — | **works** |
| Character select | done | — | **works** |
| World entry | — | done | **works** (with the disk DTLS patch + possession env) |
| In-world | — | partial | **stable but immobile** |

## Evidence

- State machine, warnings, timeouts: `Game.log` of the 2026-10-07 sessions.
- HTTP endpoints and status codes: `services/gateway/traffic.jsonl` and the
  Caddy access log (`.azoth/logs/caddy.log`).
- REP message types and sizes: `services/world/replay/messages-redacted.txt`
  parsed by `azoth_world.javelin.replay_store.ReplayStore`.
- Live channel tallies: `services/world/rep_traffic.jsonl`.
- Client functions: `atlas/client-functions.json`; decompiled bodies under
  `reverse/builds/<sha256>/campaign/<phase>/`.
