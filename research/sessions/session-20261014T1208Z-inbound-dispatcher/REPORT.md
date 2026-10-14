# 2026-10-14T12:08Z — the inbound dispatcher, live

First session with `INBOUND_DISPATCH_ENABLED` on (default). The server now decodes the client's
typed requests and acts on the ones it can answer, instead of only counting them.

## Why this exists

Until this change the server had **no inbound typed dispatcher at all**: every request the client
made was acknowledged at the transport level and then ignored, with nothing in any log saying so.
Measured over sessions: 19 requests in a short session, 29 in one that exercises more UI.

## The request shape, measured rather than guessed

Every client->server typed request is

```
[u32 BE crc32][u32 BE len][16-byte facet target][00 01][prefix-varint type][params]
```

so after the type marker the **first 16 bytes are the target facet's local id** — the address a
reply needs. `inbound-request-shape` logged the real shape of all six known requests:

| wire | name | size | target | params |
| --- | --- | --- | --- | --- |
| `0x9d3` | `PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient` | 48 | `d1a94ccc870660b0bf85314bbc4a951a` | 4 |
| `0x9fc` | `ContractsComponentServerFacet_LookupContractsByParticipant` | 102 | `4c0c0ed6478a69dabf85314bbc4a951a` | 58 |
| `0xa95` | `ObjectivesComponentServerFacet_SetObjectiveAutoPinning` | 81 | `180f8d4e573697c6bf85314bbc4a951a` | 37 |
| `0x183` | `GlobalStorageComponentServerFacet_SetReplicateStorage` | 60 | `e2640b7ce5408036bf85314bbc4a951a` | 16 |
| `0x5b2` | `ObjectivesComponentServerFacet_UpdateTrackedObjectives` | 45 | `180f8d4e573697c6bf85314bbc4a951a` | 1 |
| `0x1098` | `TimeComponentServerFacet_SyncToClient` | 44 | `93a3e477cb5fd51ebf85314bbc4a951a` | 0 |

## What the dispatcher did

1. **It learned the time facet's address from the client itself.** `0x1098` carried
   `93a3e477cb5fd51ebf85314bbc4a951a`, and the captured `0x1096` body carries the same value as
   its own target — so the reply is now addressed from the client's own request instead of from
   the capture or from a Frida probe publishing an id to a file.
   `inbound-time-target-learned: {target: 93a3e477…, serves: [0x1096, 0x1097]}`.

   Confirmed in the sends: **all 151 `input-response` events carry
   `target_source: client-request`** (not `lever-or-captured`), with `retargeted: 2` per event.

2. **It answered the contracts request — twice, once per ask.** The client asked for contracts at
   `12:08:30` and `12:08:38`; both got the captured `0x08E6` body (42 B):
   `inbound-answer: {request: 0x9fc, response: 0x8e6, size: 42, n: 1}` and `n: 2`. Before this the
   replay answered each body **once, ever**, so the second ask went unanswered.

3. **`0x08E6` moved out of the replay's one-shot set** into `DISPATCHER_OWNED_RESPONSES`, reported
   by `inbound-dispatcher-owned: {types: [0x8e6], count: 1}`. The held set fell from 32 to 31, i.e.
   the dispatcher owns exactly the one body it took over.

## Client side: nothing regressed, and the error count is unchanged

| signal | value |
| --- | --- |
| `RMIDispatch` errors | **1** — the known spawn−3 ms `GridTracking` artifact |
| distinct error types | 1 |
| `OnLocalNetworkConnectionWarning` | **0** |
| `[ERROR]` lines | 1 |
| world rendered | 26 slice lines, player possessed |

The single error is at `12:08:29.609`, i.e. **3 ms before** `player spawn succeeds` at
`12:08:29.612` — the same client-side artifact of its own spawn sequence seen in every session.

**The count is unchanged, and that is worth stating precisely rather than as an improvement.**
Since the deferral fix of 2026-10-14, four consecutive sessions each logged exactly one dispatch
error, all of them this artifact:

| session | total | `TimeComponentClientFacet` | `GridTracking` |
| --- | --- | --- | --- |
| 2026-10-13 22:05Z (before the deferral fix) | 29 | 4 | 1 |
| 2026-10-14 07:58Z | 1 | 0 | 1 |
| 2026-10-14 08:15Z | 1 | 0 | 1 |
| 2026-10-14 09:39Z | 1 | 0 | 1 |
| **2026-10-14 12:08Z (this session)** | **1** | **0** | **1** |

So the four `TimeComponentClientFacet` errors were removed by the *deferral* fix two commits ago,
not by the dispatcher; this session only confirms the dispatcher did not bring them back. The
dispatcher does now own the first send of `0x1096/0x1097` (they are no longer part of the replay
burst), but no client-side observation in this session distinguishes that from the deferral.

## Regressions checked

* **Movement:** 0.000 u baseline (87 samples), **22.998 u** with W held 5 s (29 samples, path
  23.028 — straight), 0.000 u after release (97 samples). Same numbers as the 2026-10-13 WASD run.
* **Cable:** the client's own readout at `12:11:51 / 12:12:00 / 12:12:09` read
  **498 / 265 / 266 ms**, far under the ~2 s amber threshold and refreshing.
* **ACK window:** still correct — widest range 6637, **0** ranges at/over 32768, no storm.

## What the dispatcher does NOT do yet, and why that is deliberate

The five state-carrying requests (`0x9d3` PlayerSettings, `0x5b2`/`0xa95` Objectives, `0x183`
GlobalStorage) are **decoded, counted and shape-logged but have no authoritative effect**. The
coverage line still lists them in `no_replay_response`:

```
inbound_types 43, request_types 29,
answerable_by_replay 7, no_replay_response 22,
deferred_sent 4, deferred_dropped 27
```

Inventing a reply for a setter without evidence is what this repository forbids, so the next step is
to decode each one's params from the wire and decide per request what an authoritative effect
requires — not to emit a plausible-looking message.

## Duration: NOT measured here, and the session ended on purpose

The client ran from spawn `12:08:29` to `12:13:37` — **5 min 08 s** — and it ended because the
movement probe **deliberately killed it**. `frida-player-position.py` now defaults to
`_paths.safe_shutdown(kill=True)`, which was the fix for the execute-after-unload crash, and every
world measurement wants a fresh `NewWorld.exe` afterwards anyway. So:

* nothing was lost — the probe was the last measurement of the session;
* **this session says nothing about duration.** It is not a crash, it is not a disconnect
  (`exiting to main menu` 0, `Disconnected from REP` 0), and it must not be quoted either way.
  Duration was measured in `session-20261014T0939Z-ack-window` (1 h 03 min) and the ending
  characterised in `session-20261014T0815Z-response-gating-probe-free` (1 h 06 min, client
  `SM_DISCONNECT`).

## Files

* `server-events.jsonl` — config, the six request shapes, the learned time target, the two answers,
  the dispatcher-owned handover, the coverage line and the per-response verdicts.
* `ack-audit.txt` — the ACK auditor's verdict on this session (exit 0).
* `position-samples.log` — the probe's samples with wall-clock stamps.
* `Game.log` — the client log.

> The evidence files named above (`Game.log`, `server-events.jsonl`, `ack-audit.txt`,
> `position-samples.log`) are local-only: `research/.gitignore` keeps raw captures out of
> git, so this report is the durable part. Everything asserted here is also recorded in
> `research/atlas/client-functions.json` and `STATUS.md`.
