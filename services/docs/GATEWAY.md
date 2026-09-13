# HTTPS Gateway

Python process on `127.0.0.1:8080`. Caddy terminates TLS on `:443` (SNI, ALPN h1/h2). Local CA installed on Windows for the private profile (hosts or patched URL).

## Modules (one binary, no microservices)

| Module | What it serves |
| --- | --- |
| `channel` | `STEAM_APP_ID.1063730.json` — a single cluster pointing at us |
| `cms` | news / tiles / MOTD **with ETag** |
| `omni` | `tokenservice` + `/prod/credentials/omni` (STS shape, `type=full`) |
| `remote_config` | S3 keyspace `configuration-sets/…` (SigV4 **unverified**) |
| `entitlements` / catalog / privacy | stubs |
| `characters` | getlogininfo + create (path discovered in `FTUE_V2_CC`) |
| `queue` | ticket `worldId_uuid` + `RepAddress` from `worlds.rep_host:port` |
| `discovery` | dumps unknown paths to `mock_discovery/` (gitignored) |

## Host allowlist

Single file: `deploy/hosts-allowlist.json` (added in the deploy PR). S3 remote-config **yes**. Epic, EAC, Vivox, Steam, STS **no**.

Do not adopt the 38-host catalog wholesale.

## Phase 1 criterion

Game.log: `StartREPConnection` with `RepAddress` localhost. Staying on `WaitingForREPConnection` without a world is success for this piece.
