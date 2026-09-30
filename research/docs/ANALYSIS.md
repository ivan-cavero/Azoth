# New World Private Server — Technical analysis

This document lives in **research/** (monorepo). Contract: `../../docs/ARQUITECTURA.md`. Index: [INDEX.md](INDEX.md).

Date: 2026-09-06
Analyzed client: Steam install at `C:\Program Files (x86)\Steam\steamapps\common\New World`
Build: `[RETAIL].Javelin.1.400.6031.6004151` (compiled 21 Mar 2026)
Steam App ID: `1063730`

This document is the map of the terrain. It is not a server yet. It summarizes how the game is built, how a player logs in, what must be replaced for our own backend, and a phased plan.

---

## 0. Context

Amazon delisted New World: Aeternum on January 15, 2026. Official servers shut down on **January 31, 2027**. There is no new content; maintenance only. About 5 months of live traffic remain. That traffic is unrecoverable the day they switch it off.

Today, on this machine, the client **does log in** to the official servers. `Game.log` from 14:41–14:47 (local time) shows Steam login → Omni → queue → REP → spawn → `InGame`.

| Field | Value from today's session |
| --- | --- |
| Character | `xNozus` |
| Character ID | `07631b31-78f5-419d-8be8-ddca69eecbc9` |
| Omni persona | `amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c` |
| Cluster | `fra-prod` (EU Central) |
| World | `live-1-12-2` / `86ae8332-ed32-420e-985c-61011022847a` |
| REP | `35.71.153.244:58257` (AWS Global Accelerator range) |
| AGS account type | `Shadow` |
| Ownership | `permanent` |

That changes the plan: there is no need to "guess" the login. We must **capture** this full session (HTTPS + UDP/DTLS) while Amazon is still up, and at the same time build the mock that replaces those endpoints.

---

## 1. What the client really is

### Engine

- **Amazon Lumberyard 1.12.0.1** (CryEngine fork), not O3DE.
- Game DLL: `Javelin` (`bootstrap.cfg`: `sys_dll_game = Javelin`).
- Renderer: Direct3D 12 (`RenderD3D12`).
- UI: **LyShine** gem.
- Combat: **Slayer Script** (native C++, hot-loadable).
- Data: **NewWorldDataSheet** gem.
- Terrain/world: **Coatlicue** (`CGame::InitCoatlicueTerrain`, PAK `CoatlicueStrm.pak`).
- Voice: Vivox.
- Anti-cheat: Easy Anti-Cheat EOS (`productid b0855340e2ed491096135339f6fc94b7`).
- Platform: Steam (`steam_api64.dll`).

The "modules" in `assets/Config/Game.xml` **do not exist as loose DLLs**. They are linked into `Bin64/NewWorld.exe` (~179 MB, ~133 MB of `.text`). The exe is an x64 monolith with ASLR + DEP.

Relevant internal modules:

- `EngineClient`, `EngineClientServerShared`
- `JavelinComponentsClient`, `JavelinComponentsCharacterClient`, `JavelinComponentsAIClient`
- `Gem.LyShine`, `Gem.SlayerScriptClient`, `Gem.NewWorldDataSheet`

`typeindex.json` (generated 2025-10-22) lists **7052** AZ type UUIDs. It is Lumberyard's reflection registry: components, slices, assets.

### Install layout

```
New World/
  NewWorldLauncher.exe          # launcher + EAC bootstrap
  Bin64/NewWorld.exe            # the real client
  EasyAntiCheat/                # EAC EOS
  assets/
    Config/Game.xml
    Engine.pak                  # cvars, engine assets
    GameData.pak                # materials, VFX (~648 MB, ZIP)
    DataStrm*.pak               # streaming: CGF meshes, LyShine UI, anims
    SharedDataStrm*.pak         # dynamicslices, CAF animations, datasheets
    CoatlicueStrm.pak           # terrain
    VegetationStrm*.pak
    levels/newworld_vitaeeterna/level.pak   # open world
    levels/nw_dungeon_*         # expeditions
    levels/nw_raid_* / nw_trial_* / nw_opr_* / nw_arena_*
    levels/frontend* / nw_frontend_nighthaven
  bootstrap.cfg
  engine.json                   # LumberyardVersion 1.12.0.1
```

The PAKs are **ZIP** (`PK\x03\x04`). They can be listed and extracted with any ZIP tool. That is the path to custom content, not patching the exe.

User data:

- Logs: `%LOCALAPPDATA%\AGS\New World\Game.log` (very verbose, gold for RE)
- Settings: `%APPDATA%\AGS\New World\`

### Authority

The game is **server-authoritative**. The client sends inputs; the server simulates physics, rules and AI; the client paints the result. A private server cannot be a "dumb relay": it has to simulate.

Official architecture of a world (AWS re:Invent 2021, Werner Vogels):

- 4 public **REP** (Remote Entry Points) — connection routers
- 7 EC2 **Hubs**, each owning cells of the map (non-contiguous grids)
- Instance pool for expeditions/arenas (sessions)
- "Stateless" hubs with state in DynamoDB (~800k writes / 30s at launch scale)
- Lambda/API Gateway microservices for login, characters, trading, companies
- Design ceiling: ~2500 players + ~7000 AI + hundreds of thousands of objects per world

That is Amazon's ceiling. A private server starts with **one simulation process + one HTTP gateway**. Scaling to grids/hubs comes later, once the protocol and the simulation work.

---

## 2. The login is not "skipped": it is replaced

The client has no offline mode. On startup it **always** talks to Amazon. The private server does not crack Steam or Omni: **it impersonates Amazon's endpoints** and, at the end, hands the client the IP:port of *our* REP.

### 2.1 Service map (live today)

The client starts by requesting:

```
GET https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json
```

That JSON (saved in `notes/channel_config.json`) is the directory of regions. We have it whole. Per cluster:

| Cluster | Region | Auth stack | Login gateway | Javelin Gateway CF |
| --- | --- | --- | --- | --- |
| `fra-prod` | EU Central | `2mfrik7h83.execute-api.us-east-1.amazonaws.com` | `u433g9r00c.execute-api.eu-central-1.amazonaws.com` | `d1w0bfy6smo4d1.cloudfront.net` |
| `gru-prod` | SA East | `kqqt5twsi7.execute-api.us-east-1.amazonaws.com` | `j4n6whncmi.execute-api.sa-east-1.amazonaws.com` | `d1cjlmzk0xrm0z.cloudfront.net` |
| `iad-prod` | US East | `eudbjx6mig.execute-api.us-east-1.amazonaws.com` | `0prplal5u1.execute-api.us-east-1.amazonaws.com` | `d2oeuvxi3kfsrw.cloudfront.net` |
| `pdx-prod` | US West | `q8hqllbg6k.execute-api.us-west-2.amazonaws.com` | `v7irlu1nrl.execute-api.us-west-2.amazonaws.com` | `d3bj4csovi1fe8.cloudfront.net` |
| `syd-prod` | AP Southeast | `hhf8nn71vb.execute-api.us-east-1.amazonaws.com` | `ep1m9qoir8.execute-api.ap-southeast-2.amazonaws.com` | `de4mfzk9wkelz.cloudfront.net` |

Omni metadata:

```json
"OMNI.STEAM_APP_ID.1063730": {
  "omniTokenUrl": "https://tokenservice.amazongames.com",
  "nwTokenUrl": "https://prod.newworld.com/",
  "omniStage": "prod",
  "omniGameAlias": "new-world"
}
```

Other hosts touched by today's log:

- `ags-javelin-remote-config` (S3, configs per ProductId / RegionId / CognitoId / WorldId)
- `d1hkbwzm1bktgo.cloudfront.net` (CMS: news, marketing tiles, MOTD worlds)
- `client.content-service.amazongames.com` (CMS images)
- `client.entitlementservice.amazongames.com` (ownership)
- Vivox `nwxp0euc1.vivox.com` (3D voice, can be stubbed or ignored at first)

### 2.2 Real sequence (from *this* Game.log, 2026-09-06)

```
t+0      NewWorld.exe [AZ_RETAIL_CONFIG]  FileVersion 1.400.6031.6004151
t+65s    Channel service URI
         Cluster fra-prod chosen
t+124s   AuthManager → SteamAuth → OmniSDK 1.6
         Steam session ticket (handle 2)
         Omni CreateSession OK → persona amzn1.developerPersonaId.…
         GET/POST …/prod/credentials/omni
         STS-shaped AWS creds (gateway + persona), refresh ~55 min
         CGame::OnCampfireLoginComplete  ownership=permanent
t+152s   StackConfig S3 layers (public + publicGameplay)
         GameConnection ConfigureLogin MODE_GATEWAY
t+226s   CMS news/MOTD
t+226s   ActorContainerConnect
         playerName = xNozus
         Disconnected → QueryGameUpdateCheck → QueueGameLogin → WaitingForQueuedLogin
         character 07631b31-…
         login ticket 86ae8332-…_7978b8a9-…
         World live-1-12-2
         REP Address 35.71.153.244:58257
t+231s   remote config WorldId
         ObtainREPRequirements → StartREPConnection → WaitingForREPConnection
t+231.3s REP socket connection established
t+231.4s registration response from REP
         Server version [RETAIL].Javelin.1.365.6031.6017213
         WaitingForActorGameConnection
t+231.5s actor game connection succeeds
         WaitingForSpawnPoint → spawn point found → WaitingForPlayerSpawn
         LevelInfoChanged
         load NewWorld_VitaeEterna  (unload NW_Frontend_NightHaven)
t+233.6s player spawn succeeds, in game
         state InGame
         JavelinGame::OnConnectionSucceed
         Vivox login
```

Client state machine (names from the log itself):

```
Disconnected
  → QueryGameUpdateCheck
  → QueueGameLogin
  → WaitingForQueuedLogin          # HTTP login/queue/v2, ticket + RepAddress
  → QueryForRemoteConfigClass
  → WaitingForRemoteConfigClass
  → ObtainREPRequirements
  → StartREPConnection
  → WaitingForREPConnection        # DTLS + V3 Registration
  → WaitingForActorGameConnection
  → WaitingForSpawnPoint
  → WaitingForPlayerSpawn          # LevelInfoChanged, load map
  → InGame
```

That is the contract. Our own backend has to push the client through those states, in that order, with the JSONs and packets each transition expects.

### 2.3 How to redirect the client to our server

There are **two layers**, and you need both.

**Layer A — HTTPS (auth, characters, queue, config)**

1. Hosts file (or local DNS) points Amazon's hostnames to `127.0.0.1`.
2. An HTTPS server on `:443` with a local CA installed in Windows.
3. That server answers:
   - Channel config (we can return the real JSON, or one listing a single cluster of ours)
   - `tokenservice.amazongames.com` (Omni tokens)
   - `/prod/credentials/omni` (STS-shaped credentials: AccessKeyId 20 chars `ASIA…`, secret 40, sessionToken, RFC3339 expiration)
   - entitlements
   - `/prod/game/getlogininfo/...` (worlds + characters)
   - create/validate character
   - `/prod/game/login/queue/v2/...` with `RepAddress: <our_ip>:<our_port>`
   - S3 remote-config `{}` or minimal overrides
   - Empty CMS with **ETag always present** (without ETag the client crashes)

The client **still asks for a Steam ticket**. Steam has to be open. Amazon does not need to validate that ticket: our mock does not talk to Amazon. The client uses the ticket as Omni input; the embedded Omni talks to `tokenservice.amazongames.com`, which is already ours.

`Shadow` vs `Full` account: today Omni returned `ags account type: Shadow` and a link code `REYSKJDE`. The mock must return `type: "full"` to avoid pushing the user into the Amazon account linking flow.

**Layer B — REP (the real game)**

The queue ticket contains `RepAddress`. The client opens a socket to that address. In today's session it was `35.71.153.244:58257`. The port **changes per world/session** (it is not fixed 24083). The mock picks the port.

Over that socket:

1. DTLS 1.2, cipher `ECDHE-RSA-AES256-GCM-SHA384`
2. The client carries an embedded certificate / pin. Any random self-signed cert fails with `unknown ca` / `@mm_csdkerr_transport_security_error`.
3. After DTLS: Carrier handshake (GridMate) `SM_CONNECT_REQUEST` → `SM_CONNECT_ACK`
4. Then **V3 Registration** (login ticket + character/world ids)
5. Then replicas: `Cmd_Greetings`, `Cmd_NewProxy` of the actor, `LevelInfoChanged`, spawn

Until those five things happen in order, the client stays in `WaitingForREPConnection` and after ~30 s drops the session.

### 2.4 EAC

The launcher (`NewWorldLauncher.exe`) installs and starts Easy Anti-Cheat EOS. The live Steam binary **cannot be instrumented** (Frida, DLL inject, memory patch) with EAC active.

Implications:

- A private server that pretends to be the client's backend **without patching disk** has to speak the protocol exactly as is. That is the correct way.
- Traffic capture: HTTPS mitm (hosts + CA) does not touch the process. UDP/DTLS capture at the NIC (Wireshark) does not either. Both **can be done today**, with EAC on, while playing official.
- Memory patches / Frida: only with a build launched skipping the launcher, and EAC will complain or not start. Not the MVP path.

There is no need to "bypass EAC" for an emulator. We have to **speak the client's language**.

### 2.5 What not to do

- Do not attack Amazon's API Gateways / REP.
- Do not forward Steam tickets to Amazon from a pirated server.
- Do not publish a crack of the exe.
- The goal is an **emulator** that the client you already own connects to, just like TrinityCore with WoW.

---

## 3. Game protocol (Javelin)

Javelin is a fork/rebrand of **Lumberyard GridMate**, not O3DE AzNetworking. The wire format can be read in GridMate's MIT code (`aws/lumberyard`, `Code/Framework/GridMate/`).

Layers, bottom up:

```
UDP
  DTLS 1.2  (ECDHE-RSA-AES256-GCM-SHA384)
    Carrier datagram
      [u16 BE seq] [message records…]
      optional: compression hint (0x00 / LZ4)
      4 channels; channel 3 = system (connect, acks, clock)
    Application messages
      Handshake / V3 Registration
      Replica stream:
        Cmd_Greetings, Cmd_NewProxy, Cmd_DestroyProxy,
        Cmd_NewOwner, Cmd_Heartbeat, updates per ReplicaId
      RPCs in chunks (*ComponentClientFacet / *Messages)
```

Details that matter for implementation:

- Endianness **big-endian**.
- Datagram header: 2 bytes of sequence.
- Each message: flags (reliable, chunks, channel, sequential ids) + payload.
- Acks do **not** go in every packet: they go as `SM_CT_ACKS` on channel 3.
- After DTLS, the Carrier sends `SM_CONNECT_REQUEST` (unreliable, retry backoff). The server answers `SM_CONNECT_ACK` (reliable). That is where New World carries the login ticket.
- Replicas: `ReplicaChunkClassId = CRC32(name)`. New World splits each component into `*Facet` (state) + `*Messages` (RPC) × Client/Server.
- VLQ sizes (not protobuf varint): a prefix of 1s counts extra bytes.
- Bools packed to a **bit**, not a byte.
- Spatial interest (AOI) is custom: the world is seamless and the official hubs split the map into grids.

The client, in today's spawn, already fired real RMIs:

- `EventNotificationComponentClientFacet_SyncNotifications`
- `GridTrackingComponentClientFacet_UpdatePhasing`
- `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`
- `GameModeParticipantComponentClientFacet_OnLeftQueueForGameModeMsg`

That is the living catalog of messages. `Game.log` names them. A decrypted DTLS capture (or a later hook) grounds them in bytes.

Spawn MVP, estimated from the state machine:

1. V3 RegistrationResponse accepted
2. `PlayerManagerSelfIdentification` (advances 10→11)
3. `LevelInfoChanged` (loads `NewWorld_VitaeEterna`)
4. `Cmd_NewProxy` of the player's actor (advances 13→14 `InGame`)

With that, the client enters the world. Combat, AI, inventory, crafting, war, trading: all of that is hundreds more chunks, implemented **later**, one by one, against captures.

---

## 4. Content: how the world sits on disk

| What | Where | Format |
| --- | --- | --- |
| Open world | `levels/newworld_vitaeeterna/level.pak` | Cry level (xml + terrain.dat + .bai) |
| Expeditions | `levels/nw_dungeon_*` | same |
| Raids / trials / OPR / arenas | `levels/nw_raid_*`, `nw_trial_*`, `nw_opr_*`, `nw_arena_*` | same |
| Frontend / menu | `nw_frontend_nighthaven`, `frontendv2*` | same |
| Terrain stream | `CoatlicueStrm.pak` + `coatgen/` in SharedDataStrm | dynamicslices per spatial chunk |
| Prefabs/entities | `*.dynamicslice` (~40k+ in SharedDataStrm, ~57k in part1) | Lumberyard slices |
| UI | `lyshineui/` in DataStrm | dds + uicanvas |
| Meshes | `.cgf` / `.cgfheap` in DataStrm | Cry geometry |
| Anims | `.caf` | Cry animation |
| Quest/NPC tables | `sharedassets/springboardentitites/datatables/*.datasheet` | binary DataSheet |
| Materials/VFX | GameData.pak | mtl, xml particles |

Coatlicue splits the map into chunks (`props_32x32`, `128x128`, `256x256`, `1024x1024`). The client **already has the world**. The server does not have to "send the map": it has to say "load `NewWorld_VitaeEterna`" (`LevelInfoChanged`) and then replicate actors.

Adding zones/classes is **not** a JSON on the server. It is:

1. Extract PAK → edit / create slices, datasheets, level.pak
2. Repack PAK (the client reads `PaksList.lst`)
3. Teach the server the new entity defs (the same IDs/CRCs as the client)
4. Spawn those entities by replica (`Cmd_NewProxy`)

Without the Lumberyard editor (not public for this game) new content is done blind: clone an existing slice, change IDs, datasheets. It is viable for items/stats/quests. A new zone with its own terrain is a separate art project (Coatlicue).

New World's "classes" do not exist like in WoW: there are weapons + skill trees. Adding a new weapon = weapon datasheet + Slayer Script abilities + anims + UI icons + replication of the combat component. The bottleneck is the **combat script on the server**, not the icon.

---

## 5. Target backend (modern, lag-free, scalable)

Do not copy DynamoDB + 7 hubs on day 1. Copy the **contract** with the client, and a simulation that does not lie.

### 5.1 Processes

```
                        ┌─────────────────────────────┐
   client  HTTPS        │  gateway (auth/login/CMS)   │  :443
   ───────────────►     │  Rust axum / Go             │
                        │  Postgres (accounts, chars) │
                        └────────────┬────────────────┘
                                     │ ticket + RepAddress
                                     ▼
                        ┌─────────────────────────────┐
   client  DTLS         │  REP / world sim            │  UDP
   ───────────────►     │  Rust or C++                │
                        │  tick 20–30 Hz              │
                        │  spatial hash / grid        │
                        │  interest management        │
                        └────────────┬────────────────┘
                                     │
                        ┌────────────┴────────────────┐
                        │ Redis (presence, queues)    │
                        │ Postgres (persistence)      │
                        │ instance workers (dungeons) │
                        └─────────────────────────────┘
```

### 5.2 Why this split

- 90% of the login endpoints are JSON HTTP. Easy, testable, not the hot path.
- Lag lives in the **REP**: DTLS, acks, AOI, physics, combat. That has to be a native binary, zero-copy, no GC in the tick.
- A private world of 50–200 players fits in **a single** simulation process if AOI is right (only replicate what is near).
- Expeditions: the client already loads another `level.pak`. The server spawns a worker, moves the player to another RepAddress or to an internal "instance id". Amazon used a pool of EC2; we use a pool of processes.

### 5.3 Recommended stack

| Piece | Choice | Why |
| --- | --- | --- |
| HTTP gateway | Rust (`axum` + `rustls`) | Own TLS, strict JSON schemas, one binary |
| REP / sim | Rust (tokio + rustls DTLS or openssl) **or** C++ | Deterministic tick, no GC |
| Persistence | PostgreSQL | characters, inventory, slow world state |
| Hot state | Redis or in memory + snapshot | presence, gathering locks |
| Captures | Wireshark + mitmproxy + own logger | while Amazon lives |
| Tests | fixtures of captured packets | every message gets round-tripped |

Python works for the **auth mock** and for prototyping codecs. It does not work as a 200-player simulation. The auth gateway can stay in Python at first and be rewritten once the schema is closed.

### 5.4 Simulation (so there is no lag)

Rules, not magic:

- Real **server authority**: the client sends input (WASD, skills), the server integrates and replicates transform.
- Fixed tick (e.g. 30 Hz). Inputs queued with timestamp. Do not process "last packet wins" without a short rewind.
- AOI per cell (the official map is already a grid). A player only receives replicas of their cell + neighbors.
- Unreliable for movement; reliable for inventory, quests, combat events.
- Do not replicate 100k static props: the client already has them in Coatlicue. Only live actors (players, AI, gatherables with state, projectiles).
- Physics: no need for full PhysX on day 1. Capsule + navmesh extracted from the level + combat raycasts.
- Async persistence: the tick never waits on Postgres. Write-behind.

When one process is not enough: split the map into N workers (like the 7 hubs), with actor handoff at the border. That is phase 4, not phase 1.

---

## 6. Phased plan

### Phase 0 — Capture (now, while Amazon lives)

Every day without capture is protocol lost in January 2027.

1. Leave `Game.log` rotating; copy each session to `sessions/`.
2. Wireshark at the NIC: UDP toward `35.71.0.0/16` (Global Accelerator) during a full login + 5 minutes in-world (walk, hit a dummy, open inventory, swap weapon).
3. HTTPS mitm of channel/gateway **only against our mock**, not against Amazon, when we start redirecting. While we play official, do not intercept: Amazon's pin/CA is theirs.
4. Save: queue ticket, RepAddress, version strings, state sequence.

Without this phase, the rest is blind archaeology.

### Phase 1 — Auth mock (1–2 weeks of real work)

A local HTTPS server that:

- Serves channel config
- Completes Omni + credentials
- Lists one world `Valhalla` ACTIVE / OpenWorld
- Lists or creates a character
- Returns a login ticket with `RepAddress: 127.0.0.1:<port>`

Done criterion: the client reaches `StartREPConnection` pointing at localhost. It stalls there (no REP yet) but **no longer talks to Amazon**.

### Phase 2 — REP stub (the hard part)

DTLS + Carrier + V3 + SelfIdent + LevelInfoChanged + NewProxy of the player.

Done criterion: `Game.log` says `player spawn succeeds, in game` and the client loads `NewWorld_VitaeEterna`. The character can be frozen. Doesn't matter. That is the MVP of any MMO emulator.

### Phase 3 — One player moves

Input → replicated transform. Camera, idle/walk animation. No combat.

### Phase 4 — Persistence + N players

Accounts, characters, basic inventory, seeing other players (AOI).

### Phase 5 — Game systems, one by one

Gathering, crafting, combat (Slayer), AI, quests, war, trading, dungeons. Each one is a project. Prioritized with captures.

### Phase 6 — Custom content

Datasheets + slices + (later) new levels. Only once the server already understands vanilla entity defs.

---

## 7. Reality about "building it from scratch"

Community work exists. It is no secret and there is no point pretending the map is empty:

- **OpenWorld / first-light** (Discord `discord.gg/5XzwZHFv`, historical repo `nw-private-server/first-light`). Mocked HTTPS auth. DTLS + V3 partially. Blocked on post-V3 progress (`WaitingForREPConnection` retry). The GitHub repo is marked defunct; development moved to Discord.
- **Aeternum Legacy** (another Discord, claims of character-select against their own backend, no binary patch). Treat with skepticism until proof is seen.

Using their protocol documentation (GridMate, JSON schemas, state machine) is not "copying a server": it is not repeating 8 months of Ghidra. The server, the simulation and the content are built here.

This repo must be **our** backend: gateway + REP + persistence + captures from *this* machine. Wire format specs are verified against the local `NewWorld.exe` and `Game.log`.

---

## 8. Concrete next step

The analysis has already hit the ceiling of "reading files and logs". The next useful work is engineering, in this order:

1. **Capture pipeline** on this machine (script that copies Game.log + UDP pcap of a session).
2. **HTTP gateway** (Phase 1) with the schemas the log already exposed, tested against the real client.
3. Only then DTLS/REP.

RE tools for later (once the mock is up and the client points at localhost): Ghidra over `NewWorld.exe`, search for `"ECDHE-RSA-AES256-GCM-SHA384"`, `WaitingForREPConnection`, `InstallRegistrationHook`. The exe has 133 MB of code; it is not decompiled "whole", you enter through log strings.

---

## 9. Local inventory (facts)

- `NewWorld.exe` 179 204 176 bytes, PE32+, UTC timestamp 2026-03-21 00:07:07
- EAC EOS product `b0855340e2ed491096135339f6fc94b7`
- Live channel config downloaded: `notes/channel_config.json` (5404 bytes)
- Today's `Game.log`: full official login up to InGame
- PAKs = ZIP; GameData 18 034 files; DataStrm 19 331; SharedDataStrm 65 491; SharedDataStrm-part1 65 199
- 7052 type UUIDs in `typeindex.json`
- Main map `NewWorld_VitaeEterna`; current frontend `NW_Frontend_NightHaven`
