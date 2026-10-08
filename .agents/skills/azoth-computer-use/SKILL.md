---
name: azoth-computer-use
description: Drive the visible New World window (focus, keys, clicks, screenshots, motion measurement) when a task needs to see or operate the game GUI. Prefer program state over pixels; use the measured repo toolchain, not generic GUI automation.
---

# Azoth game computer use

Use this skill to interact with the running New World window: enter the world,
press keys, click UI, capture what the player sees, and measure whether the
scene changed. It complements (never bypasses) the EAC rules in
`.agents/skills/azoth-live-debug/SKILL.md` and `research/docs/EAC.md`.

## Decide with state, observe with pixels

A screenshot is a lossy, expensive observation; a state signal is cheap and
exact. Before capturing pixels, check whether the answer already exists:

- `Game.log` (client state machine, RMIs, warnings) — ingest with
  `python az.py re ingest-log`.
- `services/gateway/traffic.jsonl` / world `rep_traffic.jsonl` (what the
  client actually sent/received).
- Probe counters (`python az.py probe list`) for component/function facts.

Take a screenshot only when the question is visual (did the menu open, is the
character rendered, did the view move). Never decide "the game ignored input"
from pixels alone when a log line or counter can settle it.

## Input channels (measured, in preference order)

| Channel | Tool | Use for | Do not use for |
| --- | --- | --- | --- |
| Window messages | `scripts/post-input.py` | Keys/clicks without stealing the user's focus or cursor | Anything the engine reads via Raw Input (movement may not register) |
| Real SendInput keys | `scripts/send-input.py` | Console (`~` = VK 0xC0), text, single keys the game ignores via messages | Holding a key |
| Real SendInput hold | `scripts/hold-key.py` | Movement (W = scan `0x11` / VK `0x57`), ~1.5 s holds | Single menu keys (overkill) |
| Real SendInput click | `scripts/click-window.py` | Game UI buttons (window-local x y) | — |
| orca computer | harness skill | Other apps (browsers, editors) | The game: its press-key cannot hold, lacks `~`, and its clicks do not reach a Raw Input window |

The game reads Raw Input; only `SendInput` with a real scan code reaches its
movement path. Window-posted input reaches menus but may not reach movement —
verify per action, one variable at a time.

## Focus: the step everyone skips

`SetForegroundWindow` is refused unless the caller is foreground; a synthetic
key then lands in whatever window the user is in (measured 2026-10-04: an
entire "W does not move" round went to Discord). Always:

1. `python scripts/focus-window.py "<title substring>" --check` — refuses if
   focus failed; never send input after a refused focus.
2. Send the input.
3. Verify the effect on state (log/counter) or a fresh screenshot.

The user shares this machine. Prefer `post-input.py` when the user may be
typing; use focus-stealing channels only for the measured action, then release.

## Screenshot pipeline

1. `python az.py shot <out.png>` — captures the game window (PrintWindow; no
   focus steal).
2. `python scripts/shrink-image.py <capture.png>` — ALWAYS; never read the
   raw PNG.
3. Read the shrunk image. It is scaled: map any coordinate back
   (`window_x = shrunk_x * window_width / shrunk_width`) before passing
   window-local coordinates to `click-window.py`.
4. Coordinates expire: after any action that changes the screen, re-capture
   before clicking again. Never click from a stale frame.

## Measure change, do not eyeball it

For "did X change the screen" questions, use `scripts/bmp-diff.py` on before/
after captures and report the motion ratio; the repo threshold for "no
movement" is ~0.12–0.13x. One action per measurement, fresh captures both
sides, and record the exact input sent (scan code, hold duration, focus
verification) with the result in the session notes.

## Known in-game surfaces (verified live)

- `change_camera` = O, `toggle_camera` = Insert, `teleport_player` = T,
  `camera_free_look` = LAlt; `debug_camera` free-fly exists but ships
  disabled (`enable="0"`, PAK edit — see `research/atlas/levers.md`).
- The game console opens with `~` (send via `send-input.py key c0`); retail
  ignores `autoexec.cfg`.
- After entering the world, require the `ProcessPendingReliableMsgQueue
  processing 26 messages` marker before interpreting any counters.

## Close the loop

Record what was sent, what the state signal showed, and what the pixels
showed; label the finding observed/validated in the relevant atlas or
client-map file. Remove one-off harness tweaks afterwards; keep the shared
scripts as the only input path.
