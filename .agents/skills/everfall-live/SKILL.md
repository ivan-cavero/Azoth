---
name: everfall-live
description: >-
  Run one measured Everfall session on the private New World client.
  Use when the next step needs the live game, a probe, or a before/after log.
---

# One session

Also load `security` and `protocols`. For keystrokes and screenshots, the computer-use notes in `azoth-computer-use` still describe the measured input tools. Prefer a log line over a screenshot.

1. State the single question.
2. Confirm the client was launched without Easy Anti-Cheat. If that is uncertain, stop.
3. `python ef.py dev` and `python ef.py game`. Steam stays read-only.
4. Change one thing. Record what the client did, the build SHA-256, and the log under `.azoth/`.
5. Update `research/atlas/meanings.md`, including a negative result. Stop.

Do not repeat a failed attempt without a new reason. Do not add Rust from one session.
