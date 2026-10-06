# Login — Steam auth handoff, gateway queue, login RMI chain

Build analyzed: pending · Status: open (partial from gateway work)

## Overview

1. Steam ticket obtained -> gateway `GetLoginInfo` chain (see
   `../../../services/gateway/README.md` and `../endpoints.json`).
2. Login queue: ticket with `RepAddress` for the world server.
3. Handoff to world-entry phase (REP DTLS).

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| (pending) | | | | |

## Client state machine

- `GameConnection` states up to `QueueGameLogin` / `WaitingForQueuedLogin`
  are named in `../../../research/docs/REP-PROTOCOL.md` ("Where REP sits in
  the login chain") — `open:` enumerate the full wrapper state enum on this
  build.

## Messages and payloads

- `getlogininfo_request_builder` (confirmed, 0x1474ea680) builds the first
  gateway request — wire facts in `../models.json` / `../endpoints.json`.
- `login_error_enum` (confirmed, 0x147fc3d08) — error table; causes in
  `../errors.json`.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| getlogininfo_request_builder (confirmed) | 0x1474ea680 (8654f01d…) | Steam ticket present | first gateway POST | client-functions.json |
| login_error_enum (confirmed) | 0x147fc3d08 | — | login error mapping | client-functions.json |

## Data and assets

- `open:` localization keys for login error toasts.

## Open questions

- `open:` complete gateway request sequence from title screen to queue ticket
  (partially covered by `../observed-endpoints.json`; gaps noted there).
- `open:` queue poll cadence and cancel conditions.

## Negative findings

- HTTPS MITM against Amazon endpoints is not viable and is forbidden; auth
  clear parts come from `Game.log` (`../../../research/docs/CAPTURE.md`).
