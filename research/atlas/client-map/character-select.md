# Character select — list, create, delete, appearance

Build analyzed: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` ·
Status: current as of 2026-10-07 (observed on a live private session).

## Overview

The screen is the `NW_Frontend_NightHaven` level with a UI canvas over it. It
renders one row per entry in the login-info character list, plus a **Play**
button that starts the world-entry ladder.

Observed flow (Game.log, 2026-10-07 21:20):

1. Frontend level loads (`Loading level NW_Frontend_NightHaven`).
2. `CGame::OnCampfireLoginComplete, login successful. ownership=permanent`
   — the persona/ownership handoff completed.
3. The panel shows the character list from `getlogininfo`.
4. **Play** → `GameConnectionWrapper::Connect` →
   `Queuing login for world () and character (11111111-1111-1111-1111-111111111111)`.
5. `Received a login ticket: <uuid>` → the world-entry ladder begins.

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| Character row | render | shows the character name and world | `getlogininfo` `LoginInfoList.Characters` | live screenshot 2026-10-07 |
| `Create Character` (×3 slots) | click | opens the create flow | `POST /characters` (+ `/characters/validator`) | UI label; endpoint in `CLIENT_CONTRACT.md` |
| **Play** | click | starts world entry | `POST /prod/game/login/queue/v2/jwt/omni` | Game.log `Queuing login …` |
| Announcements tile | render | CMS tile | `GET /marketingtiles/…/metadata.json` | `traffic.jsonl` |
| News / Events | click | CMS news | `GET /newsstories/…/metadata.json` | `traffic.jsonl` |

The screen itself makes **no REP call**; it is HTTP-only until **Play**.

## Client state machine

- The screen is entered when `GameConnection` is `Disconnected` and the
  frontend level is loaded.
- **Play** transitions `Disconnected → QueryGameUpdateCheck` and the whole
  world-entry ladder follows (see `world-entry.md`).

## Messages and payloads

| Direction | Resource | Shape |
| --- | --- | --- |
| client → server | `GET /prod/game/getlogininfo/jwt/omni?channelId=…&includeNames=true&isTrialOwner=false` | request |
| server → client | same | dual schema: camelCase worlds for the dropdown **and** a `LoginInfoList` object with PascalCase `Worlds`/`Characters` (see `LESSONS.md` §3) |

### The character list comes from `getlogininfo`, not `/characters`

Measured 2026-10-07/08 across the Caddy access log and the gateway traffic log:
the client made **0** requests to
`/characters` or `/characters/validator` in every private run. The panel
population path is the `LoginInfoList.Characters` array inside the
`getlogininfo` response.

Consequence: the gateway's `/characters` route
(`services/gateway/src/azoth_gateway/routes/characters.py`) is a **guessed shape
that the client does not exercise** in the current flow. It is kept as a
harmless fallback for a future character-create flow, but it is not on the
critical path and should not be treated as confirmed. To seed the panel, edit
`LoginInfoList.Characters`, not `/characters`.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| getlogininfo_request_builder (candidate) | 0x1474ea680 | channel/persona | the login-info request | `campaign/login/` |
| login queue ticket parser (candidate) | 0x14643d110 | `LoginQueueResponse` | ticket → `RepAddress` | `campaign/login/` |
| queue handoff gate (candidate) | 0x14114b200 | non-empty `Signature` | next state | `campaign/login/` |

## Data and assets

- Level: `NW_Frontend_NightHaven`.
- Character appearance is client-side (PAK slices); the server supplies the
  list entry, not the mesh.

## Open questions

- `open:` the create flow's substates (name check, appearance commit, confirm)
  and its exact request bodies — not exercised in the current private flow.
- `open:` where the client reads the **character UUID** it puts in the queue
  request. In the observed session it sent the placeholder
  `11111111-1111-1111-1111-111111111111`, and later logged
  `Character ID: 11111111-1111-1111-1111-111111111111`. Serving a real UUID in
  `LoginInfoList.Characters` may replace it.
- `open:` validation rules the client applies locally before sending create.

## Negative findings

- The screen does not open a REP connection and does not touch the world
  server; all of its traffic is the gateway.
- The panel renders nothing without at least one seeded character entry
  (`LESSONS.md` §4).
