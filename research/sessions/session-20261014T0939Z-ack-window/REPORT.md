# 2026-10-14T09:39Z — the ACK window fix, verified past the boundary that killed the client

A/B against the probe-free run of the same day (`session-20261014T0815Z-response-gating-probe-free`,
spawn 08:16:51, 34 min). **One variable: `ACK_WINDOW` (the sliding CT_ACKS range).** Same build,
same env, same machine, no probe attached in either run.

## The defect this run tests

The Carrier CT_ACKS is a CONTINUOUS range `[ack_first, ack_last]` in two **16-bit** fields, and
`ack_first` was pinned to the session's first inbound envelope sequence. The acknowledged range
therefore grew by one per datagram for the whole session, and once it passed **half the 16-bit
space (32768)** a wrap-aware reader can no longer tell how wide it is. The client's response is
not an error — it retransmits.

Measured onset in the pre-fix run, to the second:

| event | value |
| --- | --- |
| last inbound envelope seq below the boundary | `32767` at `08:42:44` |
| first at/above | `32768` at `08:42:44` (ACK range width `32766`) |
| first retransmitted client record | reliable seq `1836` at `08:42:45` (records 1-1835: exactly 1 send each) |

and then 140 174 inbound channel-0 records in 10 minutes carrying only **660 distinct
sequences** (212×), against 1.2× earlier in the same session.

## Result: same boundary crossed, no storm

`ack-audit.txt` (exit 0) on this run:

```
CT_ACKS we sent            : 19301
widest ACK range           : 16383  (ambiguous at 32768)
ACKs at/over the limit     : 0
inbound datagrams          : 36467   max envelope seq 36468
crossed 32768 at           : ('2026-10-14T10:05:05Z', 32768)

  wire  records  distinct  factor
   349     1727      1724    1.0x
  3639      129       129    1.0x
  3967       18        18    1.0x
```

| | pre-fix (spawn 08:16:51) | fixed (spawn 09:39:07) |
| --- | --- | --- |
| crossed 32768 | `08:42:44` | `10:05:05` |
| widest CT_ACKS range | **56210** | **16383** |
| CT_ACKS at/over 32768 | **7496** | **0** |
| wire 349 retransmit factor | **64x** (142 088 records, 2 212 distinct) | **1.0x** (3 767 records, 3 764 distinct) |
| wire 3639 retransmit factor | **15.5x** | **1.0x** |
| `OnLocalNetworkConnectionWarning` at ~29 min elapsed | ~100 and climbing at 0.8/s | **0** |
| `OnLocalNetworkConnectionWarning` for the whole session | 682 | **0** |
| server outbound rate across the onset | constant (2 626/min) | constant |
| **client session lifetime after spawn** | **11 min 46 s** (probe-killed) / 34 min 10 s (probe-free) | **1 h 3 min 7 s** |

### The window also survived the 16-bit wrap, live

Not planned for, and it is the case the design was written for. This session ran **79 616 inbound
datagrams**, so the envelope sequence wrapped past 65535, and the auditor seized the range at
`first=63234 last=14081` — still exactly **16383** wide and still under the limit. A pinned
`ack_first` could not have survived that either; the count-based window does, because it computes
the width from a monotonic datagram count rather than from a difference of wire sequences.

### Duration

**1 h 3 min 7 s** after spawn (09:39:07 → 10:42:14), still live when closed by hand, against a
34 min 10 s best for the pre-fix run of the same day and the ~12–22 min range this build had
historically shown. **This is a large effect but it is one run**, and the crash history has at
least three distinct signatures, so it is recorded as a measurement and not as "sessions no
longer crash". The causal story is plausible — the client was being made to re-send ~230 records
per second for the last third of every previous session — but causality here rests on the
one-variable A/B for the *storm*, not on the duration figure alone.

The client logged 2 `[ERROR]` lines in the whole hour, both pre-existing: the spawn−3 ms
`GridTrackingComponentClientFacet_UpdatePhasing` artifact, and one
`CameraLockComponentClientFacet: Camera Target Lock Combat Profile is invalid` (client content).
`transportError` 0, `State(InGame) is timeout` 0, `Disconnected from REP` 0.

## Why the fix is the window and not something else

Three independent server-side quantities were measured constant across the pre-fix onset, which
rules out load, transport and our own reliable stream as causes:

* outbound datagram rate: 2 626/min before and after, unchanged;
* ACK send rate: 665/min, unchanged;
* our own outbound reliable-sequence stream: no gap (two reordered pairs, no missing value).

And the A/B changes exactly one thing. The onset in both runs is the same *boundary* crossed; in
one it produces a 212× storm and in the other a 1.0× factor.

## Files

> The evidence files named below (`Game.log`, `server-events.jsonl`, `ack-audit.txt`,
> `position-samples.log`) are local-only: `research/.gitignore` keeps raw captures out of
> git, so this report is the durable part. Everything asserted here is also recorded in
> `research/atlas/client-functions.json` and `STATUS.md`.

* `ack-audit.txt` — the auditor's verdict on this session (exit 0).
* `server-events.jsonl` — config (including `ack_window: 16384`), arming, per-response verdicts,
  the inbound inventory and the coverage line.
* `Game.log` — the client log.

## Limits

* One session per arm. The retransmit factor difference is large (64× vs 1.0×) and the warning
  difference is categorical (100+ climbing vs 0), so it is not a marginal signal, but each arm
  is a single run.
* The fix bounds the range at 16384. The value is a safety margin, not a measured optimum: a
  narrower window was not tried, and a wider one (>= 32768) provably re-introduces the defect.
* `ACK_WINDOW` interacts with nothing else measured, but a session that legitimately needed to
  re-acknowledge a record older than 16384 datagrams would now miss it. At the measured ~21
  inbound datagrams/s the window is ~13 minutes deep, far beyond any observed client retransmit
  interval.
