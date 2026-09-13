# Contrato del cliente

Qué pide el `NewWorld.exe` 1.400 y qué tenemos en claro. El emulador puede implementar los servicios **como quiera** por dentro; el wire hacia el cliente tiene que parecerse a esto.

Fuente: `fixtures/live_20260906_160330/` + `schemas/live/` + Game.log de `live_20260906_160330`.

## Máquina de estados (`GameConnection`)

```
Disconnected
  → QueryGameUpdateCheck
  → QueueGameLogin
  → WaitingForQueuedLogin          # HTTP login/queue/v2 → ticket + RepAddress
  → QueryForRemoteConfigClass
  → WaitingForRemoteConfigClass    # S3 configuration-sets (5 capas)
  → ObtainREPRequirements
  → StartREPConnection
  → WaitingForREPConnection        # DTLS + V3 Registration
  → WaitingForActorGameConnection
  → WaitingForSpawnPoint
  → WaitingForPlayerSpawn          # LevelInfoChanged, carga mapa
  → InGame
```

También: `InGame → WaitingForPlayerSpawn` al cambiar de mapa (~4 s), y `InGame → Disconnected` al volver al frontend.

## JSON que ya tenemos (plaintext)

| Recurso | URL | Fichero |
| --- | --- | --- |
| Channel config | `https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json` | `schemas/live/channel.json` |
| News | `…/newsstories/STEAM_APP_ID.1063730/metadata.json` | `schemas/live/cms_news.json` |
| Tiles | `…/marketingtiles/STEAM_APP_ID.1063730/metadata.json` | `schemas/live/cms_tiles.json` |
| MOTD mundos | `…/motd/worlds_STEAM_APP_ID.1063730.json` | `schemas/live/cms_motd.json` |

CMS: **ETag obligatorio** (sin ETag el cliente crashea). MOTD se reconsulta ~cada 60 s. Locales: `de-DE-`, `es-ES-`, `es-MX-`, `fr-FR-`, `it-IT-`, `pl-PL-`, `pt-BR-`.

Channel: clusters `fra-prod` (EU, el de estas sesiones), `gru-prod`, `iad-prod`, `pdx-prod`, `syd-prod`. Omni: `tokenservice.amazongames.com`, alias `new-world`.

## Inferido del log (body aún TLS en official)

| Path | Qué vimos |
| --- | --- |
| `/prod/credentials/omni` | SteamAuth lo llama. Credenciales forma STS (`ASIA…`, secret 40, sessionToken, Expiration RFC3339). |
| `/prod/game/login/queue/v2/…` | Ticket `<worldId>_<uuid>`, `RepAddress ip:port`, WorldId, WorldName, CharacterId. Location FTUE: `@mm_loginservices_location_FTUE000`. |
| `/prod/game/getlogininfo/…` | No se imprime la URL. El frontend listó Nozusss (nuevo) y xNozus. |
| `/characters` + `/characters/validator` | Create durante mapa `FTUE_V2_CC`. Tras ~46 s: `playerName=Nozusss` + UUID nuevo. |
| S3 `configuration-sets/…` | Tamaños 190, 542, 1070, 1856, 872, 5887, 146 bytes. `{}` puede ser corto. |

## Hosts (allowlist del mock ≠ catálogo de 38)

Redirect **sí**: channel CloudFront, gateway CF EU, login/auth API Gateway fra-prod, CMS, content-service, entitlements/catalog/privacy/identity, **S3 remote-config**.

Redirect **no**: Epic datarouter, EAC CDN, Vivox, Steam, STS (salvo que dumps demuestren la llamada).

## Vivox (guardar, stubear al principio)

Login `.amazon9050-ne28.<characterId>+B.`  
SIP `sip:confctl-d-amazon9050-ne28.<grid>@nwxp0euc1.vivox.com`  
UDP vistos: 27020, 27022, 27024, 27026.

## REP

UDP DTLS 1.2 `ECDHE-RSA-AES256-GCM-SHA384`. Puerto efímero. Un cert self-signed aleatorio falla `unknown ca` / `@mm_csdkerr_transport_security_error`. En private (sin EAC) se puede **parchear el pin** en una copia del exe.
