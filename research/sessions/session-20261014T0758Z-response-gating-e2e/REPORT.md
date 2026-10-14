# 2026-10-14T07:58Z — response gating, end to end

First live session of the **request-correlated response gate** (`REPLAY_REQUEST_GATING`, new
default ON). Everything below is measured in this one session; nothing is carried over from the
unit tests.

## Env (effective config read from the session's own `config` event, not from the shell)

```
AZOTH_REPLAY_LOCAL_PLAYER_UUID = character
AZOTH_REPLAY_INPUT_RESPONSE    = 1
AZOTH_RESEND_INTERVAL_S        = 1.0
AZOTH_CHUNK_GAP_MS             = 4
AZOTH_LOG_RAW                  = 1
AZOTH_REPLAY_REQUEST_GATING    = (unset -> default 1)  -> config event says true
AZOTH_REPLAY_DEFER_TIMEOUT_S   = (unset -> default 20)
```

`replay_request_gating: true`, `replay_defer_timeout_s: 20.0`, `state_stream: true`,
`input_response: true`, `replay_local_player_uuid: "character"` — all read from
`server-events.jsonl` line 1. The runbook's rule is that the effective config is read from the
event, which is why the two new keys were added to it before this session.

## What the gate decided (server side)

`replay-response-scheduling`: **32 responses held**, types
`0x1033, 0x1067, 0x1096, 0x1097, 0x136a, 0x16a0, 0x1b88, 0x8e6, 0xca4`.
`replay-defer-start`: `held: 32, request_gating: true, deadline_s: 20.0`.
`replay-complete-quiet` at 07:59:01Z (spawn was 07:58:54.508).

### Sent (5)

| seq | wire | name | why it was allowed |
| --- | --- | --- | --- |
| 0x43 | `0x08e6` | Contracts `OnLookupContractsByParticipant` | client sent `0x09fc` |
| 0x62 | `0x1033` | GridTracking `UpdatePhasing` | client sent `0x101e`/`0x102e`/`0x102f`/`0x192c` |
| 0x65 | `0x1067` | VoiceChat `OnVoiceChatServiceRegistered` | client sent `0x066b` |
| 0x75 | `0x1096` | Time `SyncTimeChange` | client sent `0x0635`/`0x1098` |
| 0x76 | `0x1097` | Time `SyncDayPhase` | client sent `0x0635`/`0x1098` |

`0x1067` is the **behaviour reversal**: the old facet survey dropped it. It now goes out because
the client asks for it, and the client accepts it — see the error count below.

### Suppressed (27), each with its reason

| wire | count | reason | required request |
| --- | --- | --- | --- |
| `0x1b88` GlobalStorage `ReceiveStorageSearchItems` | 23 | `request-not-seen` | `0x1b7f` never sent |
| `0x16a0` Inventories `OnQueryInventories` | 2 | `request-not-seen` | `0x169d` never sent |
| `0x136a` GameModeParticipant `OnLeftQueueForGameModeMsg` | 1 | `request-not-seen` | `0x0ced` never sent |
| `0x0ca4` EventNotification `SyncNotifications` | 1 | `facet-absent` | unsolicited |

Total 27. **Run 2 reproduced this exactly, 5 sent and 27 suppressed with the same per-type
breakdown** (see `STATUS.md`), so the decisions are deterministic for this capture.

The 23 count is worth noting against the 21 recorded in an earlier draft of this file: the
capture contains **23** byte-identical `0x1b88` copies (wire 7048), and both runs suppress all
23. The number was re-counted from `server-events.jsonl` rather than from a log listing taken
mid-pump.

`0x16a0` is the second reversal: it used to be sent immediately (it was not in the old table),
and nothing the client needs came from it.

## What the client said

```
RMIDispatch "facet target ID couldn't be found" count: 1
distinct message types in those errors: GridTrackingComponentClientFacet_UpdatePhasing (1)
```

The single error is at `07:58:54.505`, i.e. **3 ms BEFORE** `player spawn succeeds`
(`07:58:54.508`) — the known client-side artifact of its own spawn sequence, identical in kind
to the previous sessions' single error. Critically:

* **no `VoiceChatComponentClientFacet_*` error**, although we now send `0x1067` → the client
  accepted the message the old policy was discarding. This is the measurement that says the
  reversal was right, not just intended;
* **no error for `0x16a0`** even though it is now suppressed → dropping it broke nothing.

After the spawn line: `[ERROR]` **0**, `transportError` **0**, `State(InGame) is timeout` **0**,
`Disconnected from REP` **0**, `exiting to main menu` **0**.

## Inbound report (the new coverage line)

```
inbound_types: 43, request_types: <see note>, answerable_by_replay: 8, no_replay_response: 35,
deferred_sent: 5, deferred_dropped: 27
```

43 distinct types — the same number as the 2026-10-13 measurement, now with a classification
behind it. **Note on this line:** it was emitted by the pre-fix code, which counted the
channel-3 Carrier records among the "waiting on us" types. `_counts_as_request` now restricts
the report to channel 0 (minus `PingMsg`/V3), with a unit test
(`test_coverage_report_counts_only_channel_0_requests`); the live line in this bundle is the
old shape and the fix is not re-measured live.

## Movement (regression check — the gate change must not have broken it)

Position read with the client's own accessor at 0.2 s (`position-samples.log`, 249 samples),
phases bounded by recorded wall-clock markers.

| phase | samples | net | path | delta (dx, dy, dz) |
| --- | --- | --- | --- | --- |
| baseline, no input | 90 | **0.000 u** | 0.000 | (0, 0, 0) |
| **W** held 5 s | 29 | **23.270 u** | 23.303 | (+10.205, −20.913, +0.002) |
| after release (settled) | 168 | **0.000 u** | 0.000 | (0, 0, 0) |

`path ≈ net` (23.303 vs 23.270) again: straight-line motion, and the player is still with no
input and stops after release. Consistent with the 2026-10-13 WASD verification.

## Cable / ALC (regression check)

The client's own readout, three samples ~10 s apart, cropped from the full frame
(`alc-response-strip.jpg`):

| sample | `Time since last response` |
| --- | --- |
| 08:04:23.340Z | **717 ms** |
| 08:04:33.671Z | **431 ms** |
| 08:04:44.005Z | **98 ms** |

All far below the amber threshold (~2 s) and refinishing on every sample, so the cable is
clear. This is the scenery-independent instrument; `measure-cable.py` on the same session
reported `absent/other` but **its crop landed on wooden beams, not on the HUD**
(`20261014T080230Z-absent-other.png` is a crop of a wall), so that tool's verdict is recorded
here as unusable for this frame rather than as the evidence.

## Duration (honest) — and the client died from MY probe, measured

| fact | value |
| --- | --- |
| spawn | `07:58:54.508` |
| client's last log line | `08:10:02.417` — a routine `[CMS] Loading CMS File`, every 60 s |
| WER crash | `08:10:41` local, bucket `1667254714238955796`, event 1001 |
| **crash signature** | `BEX64`, `P4: frida-agent.dll_unloaded`, `P6: 6ac0026b`, `P7: 0x9c7e0`, `P8: c0000005`, **`P9: 8`** (execute violation) |
| session lifetime after spawn | **11 min 46 s** |

**The crash is my own instrumentation, not the server change, and this is worth being exact
about.** The position probe attached at `08:00:53Z`, ran 60 s and detached at `08:01:53Z`; the
crash came **8 min 48 s later**. That is the documented, delayed execute-after-unload race:
`frida-player-position.py` still ended with a bare `session.detach()`, which unloads the agent
while hooks installed by the script remain reachable, and it fires only when a client thread
reaches the unmapped function — hence the delay. The signature is byte-for-byte the one already
in `STATUS.md` (`frida-agent.dll` + `0x9c7e0`/`0x9c7f4`, `P9: 8`).

Consequences, stated so nothing is over-claimed:

* the **response-gating evidence above is unaffected** — every scheduling decision was recorded
  at 07:59–08:00, the movement measurement was taken at 08:01:11–08:01:17, and the cable samples
  at 08:04:23–08:04:44, all while the client was healthy;
* the **duration is not a measurement of stability** and no soak is claimed here. This session
  died at ~11m46s from a probe, which is not evidence about the server;
* **fixed:** `frida-player-position.py` now ends through `_paths.safe_shutdown()` with `kill`
  as the default (`--keep-process` for the orderly path), so the next measurement session does
  not lose its client. **Systemic finding:** most probes under `reverse/probes/client/` still
  call `session.detach()` directly; that cleanup is larger than this change and is recorded
  here rather than done silently.

## Second run (probe-free) — validates the final code and the coverage fix

Because the run above exercised `rep.py` **before** the `_counts_as_request` fix (which is why
its coverage line has the old shape), and because a duration measurement with a probe attached
is worthless, a second session was run **probe-free** against the final code. Its measurements
are in `STATUS.md`; the files are in
`research/sessions/session-20261014T0815Z-response-gating-probe-free/`.

## Files

> The evidence files named below (`Game.log`, `server-events.jsonl`, `ack-audit.txt`,
> `position-samples.log`) are local-only: `research/.gitignore` keeps raw captures out of
> git, so this report is the durable part. Everything asserted here is also recorded in
> `research/atlas/client-functions.json` and `STATUS.md`.

* `server-events.jsonl` — the session's own events: config, arming, every held response's
  verdict with its reason, the coverage line, and the 44 `inbound-typed` records.
* `Game.log` — the client log for the session.
* `position-samples.log` — the probe's samples with wall-clock stamps.
* `alc-response-strip.jpg` — three crops of the client's own `Time since last response` readout.
* `world-rendered.jpg` — the rendered world with the full HUD.
