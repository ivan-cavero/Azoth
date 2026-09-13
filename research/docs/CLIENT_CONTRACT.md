# Client contract

What `NewWorld.exe` 1.400 asks for and what we are clear about. The emulator can implement the services **however it wants** internally; the wire toward the client has to look like this.

Source: `fixtures/live_20260906_160330/` + `schemas/live/` + Game.log from `live_20260906_160330`.

## State machine (`GameConnection`)

```
Disconnected
  → QueryGameUpdateCheck
  → QueueGameLogin
  → WaitingForQueuedLogin          # HTTP login/queue/v2 → ticket + RepAddress
  → QueryForRemoteConfigClass
  → WaitingForRemoteConfigClass    # S3 configuration-sets (5 layers)
  → ObtainREPRequirements
  → StartREPConnection
  → WaitingForREPConnection        # DTLS + V3 Registration
  → WaitingForActorGameConnection
  → WaitingForSpawnPoint
  → WaitingForPlayerSpawn          # LevelInfoChanged, loads map
  → InGame
```

Also: `InGame → WaitingForPlayerSpawn` on map change (~4 s), and `InGame → Disconnected` when returning to the frontend.

## JSON we already have (plaintext)

| Resource | URL | File |
| --- | --- | --- |
| Channel config | `https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json` | `schemas/live/channel.json` |
| News | `…/newsstories/STEAM_APP_ID.1063730/metadata.json` | `schemas/live/cms_news.json` |
| Tiles | `…/marketingtiles/STEAM_APP_ID.1063730/metadata.json` | `schemas/live/cms_tiles.json` |
| MOTD worlds | `…/motd/worlds_STEAM_APP_ID.1063730.json` | `schemas/live/cms_motd.json` |

CMS: **ETag mandatory** (without ETag the client crashes). MOTD is re-fetched ~every 60 s. Locales: `de-DE-`, `es-ES-`, `es-MX-`, `fr-FR-`, `it-IT-`, `pl-PL-`, `pt-BR-`.

Channel: clusters `fra-prod` (EU, the one in these sessions), `gru-prod`, `iad-prod`, `pdx-prod`, `syd-prod`. Omni: `tokenservice.amazongames.com`, alias `new-world`.

## Inferred from the log (body still TLS on official)

| Path | What we saw |
| --- | --- |
| `/prod/credentials/omni` | SteamAuth calls it. STS-shaped credentials (`ASIA…`, secret 40, sessionToken, Expiration RFC3339). |
| `/prod/game/login/queue/v2/…` | Ticket `<worldId>_<uuid>`, `RepAddress ip:port`, WorldId, WorldName, CharacterId. FTUE location: `@mm_loginservices_location_FTUE000`. |
| `/prod/game/getlogininfo/…` | URL not printed. The frontend listed Nozusss (new) and xNozus. |
| `/characters` + `/characters/validator` | Create during map `FTUE_V2_CC`. After ~46 s: `playerName=Nozusss` + new UUID. |
| S3 `configuration-sets/…` | Sizes 190, 542, 1070, 1856, 872, 5887, 146 bytes. `{}` can be short. |

## Hosts (mock allowlist ≠ catalog of 38)

Redirect **yes**: channel CloudFront, gateway CF EU, login/auth API Gateway fra-prod, CMS, content-service, entitlements/catalog/privacy/identity, **S3 remote-config**.

Redirect **no**: Epic datarouter, EAC CDN, Vivox, Steam, STS (unless dumps prove the call).

## Vivox (record, stub at first)

Login `.amazon9050-ne28.<characterId>+B.`
SIP `sip:confctl-d-amazon9050-ne28.<grid>@nwxp0euc1.vivox.com`
UDP seen: 27020, 27022, 27024, 27026.

## REP

UDP DTLS 1.2 `ECDHE-RSA-AES256-GCM-SHA384`. Ephemeral port. A random self-signed cert fails with `unknown ca` / `@mm_csdkerr_transport_security_error`. On private (no EAC) the **pin can be patched** in a copy of the exe.
