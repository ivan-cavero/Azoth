# Login — Steam auth handoff, gateway queue, login RMI chain

Build analyzed: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` ·
Status: **implemented and working** as of 2026-10-07 (observed end to end).

## Overview

1. Steam ticket obtained -> gateway `GetLoginInfo` chain (see
   `../../../services/gateway/README.md` and `../endpoints.json`).
2. Login queue: ticket with `RepAddress` for the world server.
3. Handoff to world-entry phase (REP DTLS).

## Observed sequence (measured 2026-10-07, `Game.log` + gateway traffic)

```
POST /games/new-world/tokens
POST /auth/platform/user/code
GET  /prod/credentials/omni
GET  /prod/game/getlogininfo/jwt/omni?channelId=…&includeNames=true&isTrialOwner=false
GET  /players/amzn1.developerPersonaId.…/games/new-world/platforms/steam/entitlements
POST /players/amzn1.developerPersonaId.…/games/new-world/platforms/steam/entitlements/sync
GET  /prod/game/worlds/list/jwt/omni
GET  ags-javelin-remote-config.s3.amazonaws.com/applications/{public,publicGameplay}/configuration-sets/…
POST /prod/game/login/queue/v2/jwt/omni?channelId=…&tokenVersion=10      # ticket
POST /prod/game/login/queue/v2/{id}/jwt/omni                            # refresh
```

Log anchors: `CGame::OnCampfireLoginComplete, login successful.
ownership=permanent`; `Received a login ticket: <uuid>`; `LogEnvironmentString:
REP Address: 127.0.0.1:9000`.

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| Title gate | any button | advances to the frontend | none | live 2026-10-07 |
| Login queue panel | automatic | `POSITION IN QUEUE n` | the queue ticket endpoint | live screenshot |
| AWS credential refresh | every ~5 min | `SteamAuth: Attempting to refresh AWS credentials` | `GET /prod/credentials/omni` | `Game.log` 21:59 |

## Client state machine

- `Disconnected → QueryGameUpdateCheck → QueueGameLogin → WaitingForQueuedLogin`
  observed on this build (see `../../docs/SERVER-CONTRACT.md` for the full
  ladder and the server obligation behind each arrow).

## Messages and payloads

- The ticket envelope is `LoginQueueResponse` (PascalCase fields). Parser:
  `FUN_14643d110` (`campaign/login/`). `Signature` must be non-empty; the
  handoff gate `FUN_14114b200` compares that string (size then memcmp) and an
  empty one never advances.
- `getlogininfo` must carry **both** schemas: camelCase worlds for the
  dropdown and a `LoginInfoList` object with PascalCase `Worlds`/`Characters`
  for the character gate (`LESSONS.md` §3).

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| getlogininfo_request_builder (confirmed) | 0x1474ea680 | Steam ticket present | first gateway POST | client-functions.json |
| login_error_enum (confirmed) | 0x147fc3d08 | — | login error mapping | client-functions.json |
| login_queue_ticket_parser (candidate) | 0x14643d110 | `LoginQueueResponse` | ticket -> `RepAddress` | `campaign/login/` |
| login_queue_handoff_gate (candidate) | 0x14114b200 | non-empty `Signature` | next state | `campaign/login/` |
| local_option_lookup (candidate) | 0x140fca4e0 | option key | compares a wire string to the option store | `campaign/login/` |

## Data and assets

- `open:` localization keys for login error toasts.

## Open questions

- `open:` queue poll cadence and cancel conditions.
- `open:` the client sends the placeholder character id
  `11111111-1111-1111-1111-111111111111` in the queue request; serving a real
  UUID in `LoginInfoList.Characters` may replace it (see `character-select.md`).

## Negative findings

- HTTPS MITM against Amazon endpoints is not viable and is forbidden; auth
  clear parts come from `Game.log` (`../../../research/docs/CAPTURE.md`).
