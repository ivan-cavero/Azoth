# <Phase name> — <one-line scope>

Build analyzed: <full SHA-256> · Status: <open | current as of YYYY-MM-DD>

## Overview

Ordered flow of what happens in this phase, as a numbered list of client
states and requests. Keep it short; detail lives in the subsections.

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| e.g. Play button | click | state X -> Y | POST /operation | file, atlas, log range |

Include hidden surfaces here too: console commands, debug hotkeys, dev menus.

## Client state machine

States, transitions, and what each transition requires. Reference
`GameConnection` / wrapper expectations here: which inputs it waits for, which
queries it issues, timeout/retry behavior.

## Messages and payloads

Direction, transport, exact keys/types/order, requiredness, cadence,
acks/retries. Canonical copies of wire facts go in `../models.json` /
`../endpoints.json`; this section links to them and adds flow context only.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |

Name tier: confirmed / candidate. VAs must match `../client-functions.json`.

## Data and assets

Slice/data PAK files, localization keys, datasheet rows this phase reads or
writes, with format references under `research/docs/`.

## Open questions

- `open:` explicit unanswered questions, one line each, with the evidence that
  would settle them.

## Negative findings

What was checked and ruled out, with evidence, so no agent repeats it.
