# 2026-10-18T22:00Z — the server enforces movement authority

The correction side, implemented and verified live. **The server follows a real player and corrects
when it should; a legitimate walk produces zero corrections.**

## The architecture, from the client's own cvars

The CLIENT owns its locomotion and corrects its own desync (`javelin.alc-correct-position-desync-*`);
the SERVER validates and reacts (`javelin-server.alc-speed-hack-fix-v2-wipe-inputs`,
`player-teleport-2d-distance-metrics-threshold`). So a correction is the server **refusing or limiting
what it accepts**, not pushing a position — this build has no working position-push channel
(`IPositionReceiver`'s apply is `ret 0`, measured).

Three layers, kept separate so each is testable without a running game:

| layer | responsibility |
| --- | --- |
| `alc.read_live_position` | the client's live position (movement buffer) |
| `MovementSimulator` / `YawAwareSimulator` | the server's **own** position and prediction |
| `CorrectionPolicy` | what the server **does** about a divergence |

## The escalation

| action | when | lever |
| --- | --- | --- |
| ACCEPT | claim plausible | adopt it |
| HOLD | claim rejected | keep the server's position; divergence recorded |
| FREEZE | past `freeze_after` violations | **stop refreshing the player state stream** — measured 2026-10-13 to freeze the client's simulation and make W do nothing |
| DISCONNECT | past `disconnect_after` | drop a client that will not converge |

It **recovers**: `recover_after` clean samples resume the stream.

## The live run

```
movement-ready        after_s 11.21   observations 257
movement-simulation   pos [9352.11, 2769.718]  samples 3518  adopted 3518  viol 0
                      fwd 0.0  lat 0.0  mean_prediction_error_u 0.0025
decisions             3, all ACCEPT
```

| measure | value |
| --- | --- |
| server's own position | **(9352.11, 2769.72)** |
| walk tracked | **23.02 u**, from (9341.44, 2790.11) |
| adopted / violations | **3317 / 0** |
| mean prediction error | **0.0027 u** |
| client errors | 0 `Failed to unmarshal`, 0 `ValidationError`, 0 `transportError`, 0 connection warnings |

**Zero corrections on a legitimate walk** is the correct result, and it is precisely what a naive
authoritative server gets wrong by rubber-banding an honest player.

## Two bugs found while wiring it

1. **`set_offset` was called every sample**, and it clears the tracker's streak (correctly — a new
   frame invalidates a streak built in the old one). The streak therefore reset forever and the
   desync **never fired**. Now called once.
2. **`movement-simulation-held` logged once per sample** because it shared a dedup flag with the
   validator, whose reference resets after a rejection and then reports the next sample as its own
   first sample. It has its own flag now.

## What this does and does not establish

**Established:** the server holds its own position, follows a real walk with a 2.7 mm prediction
error, refuses implausible movement, and has a working escalation lever (the stream freeze) that has
been measured to stop the client's simulation.

**Not established:** the escalation has never fired **live** — an honest client never violates, so
`FREEZE` and `DISCONNECT` are unit-tested only. Provoking them is tomorrow's first experiment.

## Files

* `movement-events.jsonl` — every movement event from the verified run.
* `runner.log`, `Game.log` — the run reached the world (26 slice lines) and stayed clean.
