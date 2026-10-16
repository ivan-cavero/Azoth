# 2026-10-16T01:03Z — the 2-hour soak: the session SURVIVES, the connection warning does not stay clear

One probe-free run, spawned `01:03:30`, run with the default configuration
(`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`, `AZOTH_REPLAY_INPUT_RESPONSE=1`,
`AZOTH_RESEND_INTERVAL_S=1.0`, everything else default) on the build patched at both teardown
sites.

## What passes

| measure | value |
| --- | --- |
| time in world (still logging) | **135 minutes** (spawn `01:03:25`, last `Game.log` line `03:18:34`) |
| clean window (0 of every marker) | **93.5 minutes**, until the step below |
| `ActorContainerDisconnect` | **0** |
| `Disconnected from REP` | **0** |
| `exiting to main menu` | **0** |
| `Cleanup()` | **0** |
| `transportError` | **0** |
| ACK stream (`scripts/ack-audit.py`) | **healthy** — widest CT_ACKS range 16383, 0 at/over the limit, no client type shows a retransmit storm |
| client PID | **6888, unchanged from 01:02 to the end** — no restart, so the step below is a state change in ONE process |
| world rendered | yes: third-person player possessed, no error text |

So the thresholds this project was stuck at — **20 minutes and 30 minutes** — are crossed, and the
session ran for **over two hours**. That part of the acceptance is met.

**Corrected after re-reading the sampler.** The first version of this report said "124+ minutes and
still running". The last `Game.log` line is `03:18:34` (135 min) and the client stopped responding
there; the process still existed when it was killed, so this was a hang, not an exit. The sampler
also reported `DEAD` at `03:19:33` (136 min). Both numbers are now stated precisely.

## What does NOT pass, and the new lead

**From ~94 minutes the client's InGame state times out every 30 seconds and the HUD connection
warning goes RED.** Measured onset, to the second:

| minute | event |
| --- | --- |
| `02:36:56` | the client's channel-1 record steps **once**, from **259 to 68 bytes** — measured to the second, and it is a single discrete change, not a ramp |
| `02:37:25` | the first `[GameConnection] State(InGame) is timeout : frames 10, currentTimeoutIntervalCount 1` — **29 s after the step**, i.e. exactly the watchdog's 30 s budget |
| onward | that line repeats **every 30 s** (83 occurrences) |
| `~03:07` | `scripts/watch-indicator.py` reports **RED (disconnected)**; the world is still rendered and the player is still possessed |
| `03:18:34` | the last `Game.log` line; the client stops responding |

**The client's own PID never changed** (`6888` from `01:02` to the end), so this is one process
degrading, not a new session.

The server side is *normal* across the onset. Per-minute event counts before and after (from the
world log, 02:30–02:49) show only ONE change: inbound `app-data` drops from ~1259/min to exactly
**1200/min**, which is the channel-1 record shrinking — every other emitter (heartbeat 59/min,
input-response 59/min, keepalive 59/min, state-stream 283–285/min, replay ~401/min,
outbound-app-data ~2700/min) is unchanged. So this is not the ACK defect (`ack-audit` is clean), not
a transport failure, and not a server that went quiet — the client's own input stream changed shape
and its InGame state machine stopped advancing.

**What the channel-1 stream is.** `ActionListComponentServerFacet_ReceiveInputFromClient` (wire
`0x635`, the ALC input). The committed record measured it at 119/120 B in a 2026-10-10 session; here
it ran at 313 B for 94 minutes and then stepped down to 122 B. The most likely reading is that the
client ACCUMULATES input while the server never consumes it (the `javelin.*alc-*` cvars include
`ALC-max-input-to-combine`), and the step at 02:37 is that accumulator changing state — but that is
an inference, not a measurement, and the payload of the two shapes has not been decoded.

**Next experiment.** Decode the channel-1 record's body before and after the step and diff them, then
find which of the client's `javelin.alc-*` settings governs the 313-byte form. That is the same
family as the never-opened ALC door (`+0xAA0`) and the stamp (`+0xAA8`), which this project has kept
open since 2026-10-10.

## Method notes

- **A soak must be probe-free.** The previous two sessions were ended by our own instrumentation: a
  probe's default exit kills the client, and a detach faults it (`0xc0000005` in an `unknown` module,
  the documented Frida execute-after-unload signature).
- **A marker-count watcher cannot tell "clean" from "dead".** The counts stop changing either way.
  `soak-watch.py` now records the client's PID and the elapsed time since spawn, which is how the
  124-minute figure is trustworthy; an earlier version of this measurement overclaimed 30 minutes on
  a session that had been dead for six.
- **The indicator is the only instrument that sees the HUD.** It caught the red warning at 03:07
  while every server-side emitter was still healthy and `Game.log` had zero transport errors.

## Files

- `.azoth/night/soak4.jsonl`, `soak4.log` (the sampler), copied here
- `soak-2h.png` / `.small.jpg` — the world at 124 minutes with the red warning visible
- `scripts/ack-audit.py` output: healthy
- `services/launcher/runtime-tools/patch-exit-to-menu.py` — both teardown sites NOPed