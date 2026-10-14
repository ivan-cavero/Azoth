# 2026-10-14T15:49Z — the server composes the player's own state bundle

The first place the server **owns** the bytes rather than forwarding captured ones. Two runs, one
question each:

* **run A** (15:35Z): the authoritative path on, no override — does recomposition change anything?
* **run B** (15:49Z): the authoritative path on **with a field override** — does the client accept
  state the server wrote? (The file is run B's; run A is cited from the same log's events.)

## The grammar this rests on, derived from the client rather than guessed

`reverse/probes/client/frida-fragment-grammar.py` hooks the record reader (`FUN_146af20d0`), the
fragment reader (`FUN_146af2340`) and the shared prefix-varint reader (`FUN_14087b5c0`), and logs
each fragment's offset from the record start plus every varint read inside it. That settles the
grammar:

```
fragment = [varint key][varint type_index][payload]     NO length field
payload length is implied by the type
```

The record-1 (local-player metadata) bundle's nine fragment boundaries are therefore **recorded
protocol data**, not a computation:

| # | offset | size | key | type | payload |
| --- | --- | --- | --- | --- | --- |
| 0 | 2 | 58 | 55 | 4176 | 55 |
| 1 | 60 | 3895 | 19 | 3133 | 3892 |
| 2 | 3955 | 340 | 73 | 5606 | 337 |
| 3 | 4295 | 6 | 9 | 3935 | 3 |
| 4 | 4301 | 197 | 72 | 5485 | 194 |
| 5 | 4498 | 837 | 74 | 5691 | 834 |
| 6 | 5335 | 51 | **16** | **11** | 49 |
| 7 | 5386 | 1739 | 22 | 3857 | 1736 |
| 8 | 7125 | 29 | 44 | 4236 | 26 |

Cross-check: the same probe run reproduced those nine offsets **21 times**, and the (key, type)
pair it reported for each fragment matches an independent byte-level parse of the payload. Two
methods, same answer. Stored as `research/derived/state-bundle-fragments.json`.

## Run A: recomposition is byte-exact

With `AZOTH_STATE_AUTHORITATIVE=1` and no override, the server rebuilt the player's bundle from its
fragments on every send and compared the result with the captured bytes:

| measure | value |
| --- | --- |
| `state-authoritative` events | **487** |
| of those, `identical: true` | **487** |
| `state-authoritative-failed` | **0** |

So switching the authoritative path on **cannot** change behaviour by accident — the identity is
asserted on every send, not hoped for — and a layout that stopped matching the build would log
`state-authoritative-failed` instead of sending something wrong.

## Run B: the client accepts state the server wrote

`AZOTH_STATE_OVERRIDE=key=16,off=8,hex=010203` replaces three bytes inside fragment key 16:

| measure | value |
| --- | --- |
| `state-authoritative` events | **672**, all `override_applied: true` |
| logged transition | `override_from: "0975bf"` → `override_to: "010203"` |
| `state-authoritative-failed` | **0** |
| client `Failed to unmarshal` / `ValidationError` | **0** |
| client `RMIDispatch` errors | **1** — the known spawn−3 ms `GridTracking` artifact |

The client therefore parses and applies a bundle **whose bytes we composed**, with no new complaint.
The world renders normally: the same village, full HUD, NPCs, the possessed player.

Note what this run does **not** prove: it does not show the overridden value taking a visible
effect, and I did not decode the field's meaning (see Limits). It proves the machinery.

## Regressions checked (run A, probe-free for the cable)

* **Movement:** baseline **0.000 u** (33 samples) → **27.142 u** with W held 5 s (32 samples, path
  27.142 — straight) → **0.000 u** after release (162 samples). Stronger than the previous session's
  22.998 u.
* **Cable:** the client's own readout at 15:38:59 / 15:39:10 / 15:39:20 read **67 / 330 / 433 ms**,
  far under the ~2 s amber threshold and refreshing.
* 0 `transportError`, 0 `State(InGame) is timeout`, 0 `Disconnected from REP`.

## Why `key=16` was the field chosen

Across the four captured copies of the record-1 bundle, the payloads are identical except for
**exactly three bytes**, at payload offsets 5345-5347, and both values differ per copy
(`0975bf` vs `0aa7c2`). Those three bytes fall inside fragment key 16. It is the only field the
capture itself proves is live state rather than a constant, which makes it the right first target —
and a test asserts that this is still true, so the constant cannot silently drift.

## Files

* `server-events.jsonl` — run B's config (`state_authoritative`, `state_override`,
  `state_player_boundaries`), every `state-authoritative` verdict with its `override_from`/
  `override_to`, the dispatcher's events and the coverage line.
* `position-samples.log` — run A's movement samples with wall-clock stamps.
* `Game.log` — run B's client log.

> `Game.log`, `server-events.jsonl` and `position-samples.log` are local-only:
> `research/.gitignore` keeps raw captures out of git, so this report is the durable part.

## Limits, stated plainly

* **The overridden field's MEANING is not decoded.** `key=16, type=11` is a 3-byte field inside the
  local player's metadata record that the capture shows varying. Its semantics are unknown; the run
  establishes that we can write it and the client accepts it, not what it does. Nothing in the
  client's log or HUD changed between run A and run B under it, so either it is cosmetic state or
  the value `010203` happens to be inert.
* The authoritative path composes **one** record (record 1) from **one** record's worth of
  fragments. The other records in the stream are still forwarded verbatim.
* The boundaries are a constant tied to this build's record-1 layout. A build change would make the
  fragment count mismatch, which is why that case raises and is tested.
* `AZOTH_STATE_AUTHORITATIVE` defaults to **0**. The path is proven, not yet adopted as the default.
