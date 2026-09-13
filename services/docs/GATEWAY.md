# Gateway HTTPS

Proceso Python en `127.0.0.1:8080`. Caddy termina TLS en `:443` (SNI, ALPN h1/h2). CA local instalada en Windows para el perfil private (hosts o URL parcheada).

## Módulos (un binario, no microservicios)

| Módulo | Qué responde |
| --- | --- |
| `channel` | `STEAM_APP_ID.1063730.json` — un solo cluster apuntando a nosotros |
| `cms` | news / tiles / MOTD **con ETag** |
| `omni` | `tokenservice` + `/prod/credentials/omni` (forma STS, `type=full`) |
| `remote_config` | keyspace S3 `configuration-sets/…` (SigV4 **sin verificar**) |
| `entitlements` / catalog / privacy | stubs |
| `characters` | getlogininfo + create (path se descubre en `FTUE_V2_CC`) |
| `queue` | ticket `worldId_uuid` + `RepAddress` de `worlds.rep_host:port` |
| `discovery` | dump de paths desconocidos a `mock_discovery/` (gitignored) |

## Allowlist de hosts

Único fichero: `deploy/hosts-allowlist.json` (se añade en el PR de deploy). S3 remote-config **sí**. Epic, EAC, Vivox, Steam, STS **no**.

No usar el catálogo de 38 hosts al por mayor.

## Criterio Fase 1

Game.log: `StartREPConnection` con `RepAddress` localhost. Quedarse en `WaitingForREPConnection` sin world es éxito de esta pieza.
