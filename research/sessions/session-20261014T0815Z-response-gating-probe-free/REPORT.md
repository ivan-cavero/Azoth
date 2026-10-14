# 2026-10-14T08:15Z — response gating, probe-free, and the longest session measured so far

Second run of the day, started specifically because (a) the first run exercised `rep.py` before
the `_counts_as_request` fix and (b) **a duration measurement with a probe attached is worthless**
— run 1's client was killed by the position probe.

**No probe was attached at any point in this session.**

## Env

Identical to run 1 (`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`, `AZOTH_REPLAY_INPUT_RESPONSE=1`,
`AZOTH_RESEND_INTERVAL_S=1.0`, `AZOTH_CHUNK_GAP_MS=4`, `AZOTH_LOG_RAW=1`), with the final code
including the `_counts_as_request` coverage fix.

## The gate: reproduced exactly

| | run 1 | run 2 |
| --- | --- | --- |
| held | 32 | **32** |
| sent | 5 | **5** (`0x8E6`, `0x1033`, `0x1067`, `0x1096`, `0x1097`) |
| suppressed | 27 | **27** (23× `0x1B88`, 2× `0x16A0`, 1× `0x136A`, 1× `0x0CA4`) |
| client `RMIDispatch` errors | 1 | **1** (`GridTracking`, spawn−3 ms) |

The decisions are deterministic for this capture. Per-type reasons in `server-events.jsonl`.

## The fixed coverage line, measured

```
inbound_types 50, request_types 29,
answerable_by_replay 7  ['0x101e','0x102e','0x102f','0x1098','0x192c','0x66b','0x9fc']
no_replay_response  22  all channel-0 requests
deferred_sent 5, deferred_dropped 27
```

Compare with run 1, whose line (pre-fix) listed 13 channel-3 Carrier records as "waiting on us".
The 22 real unanswered requests are the actionable list.

## Duration: **34 min 10 s**, the longest session measured on this build

| fact | value |
| --- | --- |
| spawn | `08:16:51.061` |
| last client log line | `08:51:01.068` → **34 min 10 s** |
| spawn → last `[ERROR]` | never; last error at `08:45:43` |
| `transportError` / `State(InGame) is timeout` / `Disconnected from REP` / `exiting to main menu` | **0 / 0 / 0 / 0** |
| world server while the client ran | steady ~59 heartbeats, ~285 state-stream, ~59 input-response, ~59 keepalive per minute, right through 08:48 |
| state-stream `wire_seq` | 128 → 9644, monotone, **0 decreases** (no wrap, no anomaly) |

This is **more than the previously documented maximum** (`STATUS.md` recorded sessions dying at
~12–22 min by at least three crash signatures). It is still **not a 2-hour soak**, and it is one
session, so it does not overturn the crash history — it shows the response-gating change did not
shorten the session and that a probe-free run can outlive the range.

### The one thing that changed at 27 min, and what it does NOT mean

`OnLocalNetworkConnectionWarning countReceived` climbs from the very first second (count 1 at
spawn+1s, accumulating slowly at ~1 per 16 s), and at **+27 min 14 s it accelerates about 24×**:

| window | rate |
| --- | --- |
| count 1 → 101 | 1633 s (**16.33 s** per warning) |
| count 101 → 201 | 69 s (**0.69 s** per warning) |
| 201 → 301 / 301 → 401 / 401 → 682 | 0.77 / 0.85 / 0.78 s per warning |

The onset is at `08:44:05`, i.e. `spawn + 27 min 14 s`. **It is not a connection failure**, and
this was checked rather than assumed:

* the client's own derived flag is **`Client.ConnectionWarning: 0` in all 19 occurrences**, and
  the client keeps re-asserting 0 (`UpdateWarnings setting "Client.ConnectionWarning": 0`);
* `transportError` 0, `State(InGame) is timeout` 0, `Disconnected from REP` 0;
* the server keeps emitting at its normal rate throughout, including after the jump;
* the state stream's `wire_seq` is monotone with no wrap, so it is not a counter exhaustion.

So: a cumulative warning counter that accelerates at ~27 min while the client's own warning flag
stays clear and the transport stays healthy. **Recorded as an open observation, not diagnosed.**
It is roughly where the historical "~20-minute return-to-menu path" sits, which makes it worth
one targeted experiment later (one variable: raise
`AZOTH_REPLAY_STATE_STREAM_PLAYER_PERIOD_S` from 0.25 to ~1.0 and see whether the onset moves).

## The 6 `[ERROR]` lines, attributed

| count | line | whose |
| --- | --- | --- |
| 1 | `RMIDispatch` `GridTrackingComponentClientFacet_UpdatePhasing` at spawn−3 ms | known client artifact |
| 2 | `SlayerScriptComponent: Attempted to reference an unknown entity` | client content/GDE (missing world data) |
| 3 | `CameraLockComponentClientFacet: Camera Target Lock Combat Profile is invalid` | client content/config |

Only the first is protocol-related, and it is the same single pre-existing error as before. Neither
of the other two families appears in the response-gating path.

## Files

> The evidence files named below (`Game.log`, `server-events.jsonl`, `ack-audit.txt`,
> `position-samples.log`) are local-only: `research/.gitignore` keeps raw captures out of
> git, so this report is the durable part. Everything asserted here is also recorded in
> `research/atlas/client-functions.json` and `STATUS.md`.

* `server-events.jsonl` — config, arming, every held response's verdict and reason, the coverage
  line, and the `inbound-typed` inventory.
* `Game.log` — the full client log for the 34-minute session.

## Honest limits

* One session. Not a soak, and not a claim that the crash history is over.
* The 27-minute warning acceleration is **unexplained**; only the onset time and the fact that it
  is not a transport failure are measured.
* Run 1's movement and cable checks stand for the **scheduling** change (same code path); they were
  not repeated here because repeating them needs a probe.
