# 2026-10-18T09:24Z — desync detection verified live, and the first design was wrong

Two live runs, one code change between them, one question: **does the movement observer read
the client's claim and detect divergence correctly?** Answer: yes, after a correction that
only a live run could have forced.

## Run 1 — the observer works, and it immediately reports a false positive

Env: the three mandatory variables (`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`,
`AZOTH_REPLAY_INPUT_RESPONSE=1`, `AZOTH_RESEND_INTERVAL_S=1.0`), plus
`AZOTH_MOVEMENT_OBSERVE=1` (default).

```
movement-ready      after_s 13.115   observations 291
movement-desync     error_u 4.031    threshold_u 2.0   streak 5
                    claim (9341.441, 2790.110)   truth (9343.642, 2786.733)
```

The load gate fired at **t+13.115 s**, inside the 8–14 s band predicted from the captured
corpus, and the client's channel-1 stream was present (**1,342 records**). Both halves of the
reader were therefore confirmed live.

The desync, however, was **not** a desync. Re-reading all **2,562** channel-1 claims over the
next two minutes against the server's truth gave an error of **exactly 4.0311 u in every
sample**, with a **single distinct position** — the player never moved. A perfectly in-sync
player sat permanently above a 2.0 u floor.

That error is the instrument offset. The first `DesyncTracker` had argued in its own docstring
that no offset was needed because the wire claim and the server's position were "the same
quantity in the same frame of reference". **The live run refuted that premise**: they differ by
a constant, and 4.0311 u is precisely the offset measured independently against the client's
own `nw_getPlayerPosition` accessor (`(-2.200, +3.378)`).

## The correction

The offset is now part of the comparison, and the consequence is a hard rule rather than a
tuning knob:

* `ReferenceOffset` calibrates it per session from paired samples, with **no probe** — at
  spawn the client is where the server put it, so the constant difference over the first
  samples *is* the offset.
* A calibration whose samples are not tightly clustered is **rejected, not averaged**: a
  wrong offset silently hides real divergence, which is worse than having none.
* `DesyncTracker` **fails open while uncalibrated**. With the offset unknown, a 4 u difference
  is indistinguishable from a real divergence, so any verdict would be a guess. It returns
  IGNORE with an explicit "uncalibrated" reason.

## Run 2 — the same session shape, with the correction

```
movement-ready       after_s 14.488   observations 310
movement-calibrated  offset (-2.2002, +3.3777)  magnitude 4.0311  residual 0.0000  samples 20
                     -> NO movement-desync
```

The false positive is gone. The calibrated offset `(-2.2002, +3.3777)` reproduces the
independently measured captured-session offset `(-2.200, +3.378)` to four decimals, from a
completely different data path.

## The positive half — a real divergence IS detected

A detector that never fires is not a detector. With the offset already fixed, `W` was held for
3 s (`scripts/hold-key.py "New World" 0x11 3`). The player moved and the server's truth stayed
frozen at the spawn position, because the server still has no authority over the position over
time:

```
movement-desync   error_u 3.342   streak 5
                  claim (9342.902, 2787.105)   truth (9343.642, 2786.733)
```

After subtracting the calibrated offset, that is **3.342 u of real divergence**, and the
tracker reported it once rather than per sample. This is the honest shape of the current
system: the server detects that it has lost track of the player, and cannot yet correct it.

## The attempt that failed first, and why it matters

The first launch of this session never entered the world: `InGame` was reached but `Slice`
lines stayed 0, the screen stayed black, no channel-1 record ever arrived, and
`OnLocalNetworkConnectionWarning` climbed 1→4. The cause was **gate 6**: `python az.py dev` was
started without `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`, and that variable's default is the
failing value. This is the documented trap — `az.py dev` forwards whatever `AZOTH_*` the
calling shell happens to have, so a missing variable is a silently different experiment rather
than an error. A fresh `NewWorld.exe` was required, because a failed attempt destroys that
process's `ClientContext`.

## What this does and does not establish

**Established:** the reader works live (channel 1, 1,342 records); the load gate lands at
13.1 s and 14.5 s in two independent runs, against a 60 s timer that cannot see the
difference; the instrument offset is real, constant within a session, and reproducible from
two independent paths; desync detection is quiet when in sync and fires on real divergence.

**Not established:** that the desync is *corrected*. Correction is still spawn-only. The
3.342 u event is a measurement of the gap, not a repair. Nothing here shows the HUD cable
clear or the session surviving past the recorded 1 h 06 min teardown.

## Files

* `movement-events.jsonl` — the five events quoted above, verbatim.
* `runner.log` — the launcher's verdict for run 2 (`world streaming, 26 slice lines`).
* `Game.log` — the client log for run 2.

> Raw captures are local-only (`research/.gitignore`); this report is the durable part.
