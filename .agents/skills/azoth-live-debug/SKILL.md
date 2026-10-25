---
name: azoth-live-debug
description: Run a repeatable local New World/Azoth game experiment when a user asks to investigate behavior in the live private client.
---

# Azoth live debugging

Use for an explicitly requested local client or world-server A/B experiment.
This skill does not authorize starting the game, sending input, changing
Windows routing, or attaching instrumentation when the task is only static
analysis or repository cleanup.

## Before an attempt

- Read `STATUS.md`, `research/docs/WORLD-DEBUGGING.md`, and the relevant
  entries in `research/atlas/levers.md`.
- Identify one question and one variable. Prefer static analysis, captured
  server logs, or an existing fixture if they can answer it without a game
  restart.
- Revalidate the installed build and confirm EAC is inactive before any
  Frida/debugger/memory operation. If the state is uncertain, use static and
  server-side evidence instead.
- Keep official routing and the private client separate. Do not change host
  routing or launch the game unless the user asked for that live operation.
- Check the host route with `python ef.py mode status`; separately verify that
  only one gateway, world server, and Caddy process is serving the attempt.

## Measure one clean attempt

- Each world A/B variant needs a fresh `NewWorld.exe`; the failed client does
  not recreate its `ClientContext` for another attempt.
- Record the process id and the `%LOCALAPPDATA%\AGS\New World\Game.log`
  boundary. The game ignores the launcher's `LOCALAPPDATA` override, so the log
  is under the real profile, not `private-client/profile/`; see
  [`PRIVATE-CLIENT-RUNBOOK.md`](../../research/docs/PRIVATE-CLIENT-RUNBOOK.md). Treat counters as
  meaningful only after the log shows
  `ProcessPendingReliableMsgQueue processing 26 messages`.
- Set `AZOTH_LOG_RAW=1` on the world server when distinguishing missing UDP
  packets from DTLS rejection. The combined `ef.py dev` process does not inherit
  ad hoc environment changes made in another shell.
- Snapshot a run with `scripts/capture-world-run.py`. Do not truncate or rewrite
  an append-only traffic log while its service is running.
- For screenshots, run `scripts/shrink-image.py` before opening the image.

## Close the loop

Compare the single changed variable against the baseline and state which layer
the evidence reaches: UDP, DTLS, Carrier ACK, application reader, bundle,
entity/component creation, or local-player behavior. Update the focused atlas
entry or symbol record immediately. If the predicted signal did not occur,
check that the attempt and instrumentation were live before rejecting the
hypothesis. Do not start another variant until that discrepancy is explained.
