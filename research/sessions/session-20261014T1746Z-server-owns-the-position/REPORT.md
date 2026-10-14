# 2026-10-14T17:46Z — the server owns the player's position

The authoritative effect the previous session's negative result pointed at, now measured: the
server wrote a position into the state it sends, and the client's own accessor reported **exactly
that position**.

## Where the position actually lives, and why it never moved

The position is **not** in the 7154-byte record-1 bundles the state stream sends. It is in the
**46393-byte** record-1 bundles — the spawn record, 48 fragments, replay seq `0x2a..0x6c` — which
sit **below** the stream's `MIN_SEQ` floor of `0x94` and are therefore sent once by the replay and
never again. That is the whole reason the client's position stayed anchored at the capture's value
for the entire history of this project.

Found by **value, not by a guessed offset**: searching the spawn payload for the client's own
frozen position as big-endian float32 finds its first two components at payload offset 38332,
byte-exact:

| component | value | where |
| --- | --- | --- |
| x | `9343.6416015625` | payload offset 38332, f32be |
| y | `2786.732666015625` | payload offset 38336, f32be |
| z | `87.538` | **not in the payload** in any encoding tried |

The z search covered f32/f64 big- and little-endian and scaled i16/i32/i64 at x1/x10/x100/x1000/
x1024, with zero hits. So the wire carries a **2D** position and the client derives the height —
which the experiment below then confirmed independently, because the z it reported kept changing
while x and y were pinned to what we sent.

## The experiment

Env: the mandatory three plus `AZOTH_STATE_POSITION=9353.7227,2766.0681`. The value was chosen
because the client itself had reported it in an earlier session after walking, so it is a known
walkable point ~23 u from the capture's spawn.

Server side, from the session's own events: **24 `state-position-override` events, each
`replacements: 1`**, on seq `0x2a`, `0x2b`, `0x2e`, `0x2f`, `0x30`, `0x33` … — exactly the spawn
bundles, and nothing else. The override is anchored on the measured capture value, so it fires only
in a body that actually carries the position.

Client side, read through its own accessor (`nw_getPlayerPosition`'s handler):

| measure | value |
| --- | --- |
| client's reported position | **(9353.72265625, 2766.068115234375, 87.5379638671875)** |
| distance to the position the server wrote | **0.0000 u** |
| distance to the capture's position | **22.9925 u** |
| distinct z values across all 199 samples | 18, from 87.432 to 87.611 |

**The client took the server's position.** 0.0000 u from what we wrote, 22.99 u from what the
capture carried — there is no ambiguity about which one it used.

And it is a *starting point*, not a freeze: with W held 5 s from there the player moved
**14.005 u** (path 17.077) and stopped again after release (net 0.000 u over 120 samples).

## The z, resolved

The earlier session could not tell whether the client derives the height or keeps the capture's.
This run answers it: z **varies across samples** (87.432 … 87.611) while x and y sit exactly on the
values we sent. So the client computes the height itself, which is consistent with the wire
carrying only two floats.

## Nothing regressed

| signal | value |
| --- | --- |
| `RMIDispatch` errors | **1** — the known spawn−3 ms `GridTracking` artifact |
| `OnLocalNetworkConnectionWarning` | **0** |
| `Failed to unmarshal` / `ValidationError` | **0** |
| `transportError` / `State(InGame) is timeout` / `Disconnected from REP` | **0 / 0 / 0** |
| world rendered | 26 slice lines, player possessed |

## A launcher defect found on the way, and fixed

The first attempt at this session failed with `FAIL: window never appeared`. The cause was not the
client: **Windows PowerShell 5.1 on this machine loads `Microsoft.PowerShell.Utility` but does not
expose `Get-FileHash`**, which `Start-NwPrivate.ps1` calls to record the client's source hash. The
launcher died with `The term 'Get-FileHash' is not recognized` and the window never appeared, which
`private-run.py` reports as a client failure. `pwsh` 7 is installed and the runbook already records
that it, not 5.1, is the shell this script needs. `az.py` and `scripts/private-run.py` now prefer
`pwsh` when it exists and fall back to `powershell.exe`, so a machine without pwsh behaves exactly
as before.

## Files

* `server-events.jsonl` — the config (`state_position`, `state_position_captured`), all 24
  `state-position-override` events, the dispatcher's events and the coverage line.
* `position-samples.log` — the probe's samples with wall-clock stamps (199 across the two runs).
* `Game.log` — the client log.

> The evidence files named above are local-only: `research/.gitignore` keeps raw captures out of
> git, so this report is the durable part.

## Limits

* **One session, one injected value.** The result is categorical (0.0000 u from ours, 22.99 u from
  the capture's) rather than marginal, but it is a single run.
* The override writes **x and y only**. The client derives z, so the server does not yet decide the
  height — it decides where in the plane the player is, and the client puts it on the ground.
* The position is applied **at spawn** from the spawn record, which the replay sends once. The
  server does not yet stream a position continuously, so this is authority over the starting point,
  not over the player's position over time.
* `AZOTH_STATE_POSITION` defaults to empty, so the capture's position is used unless it is set.
