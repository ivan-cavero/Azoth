# Launch — engine startup, title screen, settings bootstrap

Build analyzed: pending · Status: open

## Overview

1. Process start -> engine systems init (known crash point:
   `frontend_splash_loop_after_livekernelfault_20261005` in
   `../client-functions.json`).
2. Splash loop -> "press any key" gate -> main menu entry.
3. Settings bootstrap (local options store).

## UI surfaces (exhaustive)

| Surface | Trigger | Client behavior | Server interaction | Evidence |
| --- | --- | --- | --- | --- |
| (pending — first campaign batch over this phase) | | | | |

Candidate leads: `python az.py re pe str` for splash/press-any-key strings;
`local_option_store_thread_local` / `local_option_lookup` for settings boot.

## Client state machine

- `open:` states between process start and "press any key" (candidate anchor:
  `javelin_frame_tick_driver` tick phases).

## Messages and payloads

- None expected to Amazon before user input, unverified — `open:` confirm via
  gateway traffic.jsonl on a fresh private launch.

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| javelin_frame_tick_driver (confirmed) | 0x145aa23f0 (8654f01d…) | queued frame jobs | startup phase progression | client-functions.json |

## Data and assets

- `open:` which boot slices/settings files load before the title screen
  (`pakindex` under `python az.py re pak-index`).

## Open questions

- `open:` full order of engine service init and which failures show the
  LiveKernelFault splash loop.

## Negative findings

- (none recorded yet)
