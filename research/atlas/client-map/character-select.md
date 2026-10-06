# Character select — list, create, delete, appearance

Build analyzed: pending · Status: open

## Overview

1. Character list render.
2. Create flow (name, appearance, origin) -> commit.
3. Delete flow -> confirm.
4. Enter-world trigger passes to world-entry phase.

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| (pending — no campaign targets yet for this phase) | | | | |

Candidate leads: `python az.py re pe str "create character"` and appearance
strings; `uicanvas_type_ctor` / `uicanvas_binary_layout` for the screen
canvas.

## Client state machine

- `open:` create-flow substates (name check, appearance commit, confirm).

## Messages and payloads

- `open:` character list/create/delete request-response schemas — none
  observed yet in `../models.json`.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| (empty — fill from campaign batches) | | | | |

## Data and assets

- `open:` character appearance data source (PAK slices vs server payload).

## Open questions

- `open:` validation rules the client applies locally before sending create
  (name rules, appearance limits).

## Negative findings

- (none recorded yet)
