# 2026-10-16T22:45Z — closing server-authoritative movement: read, validate, detect desync

The desync topic, closed. The result is a full account of what server authority over movement means
**in this build**, including the part that is not possible and why.

## The chain

| step | what | status |
| --- | --- | --- |
| **1. OBSERVE** | `javelin/alc.py` reads the client's own position from channel 1 (wire `0x635`) | **works** |
| **2. VALIDATE** | `movement.MovementValidator` — windowed speed + dt-independent teleport | **works** |
| **3. DETECT DESYNC** | `movement.DesyncTracker` — the client's claim vs the server's belief | **works** |
| **4. CORRECT** | push a position into the client | **unavailable — four measurements** |

### 1. Observe

Container `[u32 crc32][u32 len][16-byte target][00 01][varint type]` → body at 28. The body begins with
another 16-byte local id (the server facet the client calls) then a header and N buffered input entries,
whose grammar is not decoded. Every body that carries a position contains the 4-byte constant
`3d 4c cc cd` (**0.05f**, the client's own movement-quantization value) **exactly once**, and the pair is
**always 12 bytes after it**, as big-endian float32 — over 6 000 live bodies.

Accuracy, against the client's own accessor (`frida-player-position`, the `nw_getPlayerPosition`
instrument):

| measure | value |
| --- | --- |
| offline, 6 559 paired samples | median **0.54 u** standing, **0.81 u** walking (offset removed) |
| live | 4.03 u raw → **0.73 u** after removing the median offset |
| direction of movement | matches to **0.3°** |

The offset is **geometric, not a lag**: a lag sweep over −0.3…+2.0 s left the median flat.

### 2. Validate — and the three artifacts that had to be excluded first

The first version flagged 17–24 times in a session that was walking normally. Every flag was an
artifact, and each is now excluded by a **measured** number:

| artifact | measured | exclusion |
| --- | --- | --- |
| world-load transition | genuine 40–73 u/s samples for **~57 s** after the stream armed | `SETTLE_S=60` (was 10 s) |
| bursts | datagrams drained back to back; one flag had `dt=1.4 ms` and a 0.28 u step → reads as **204 u/s** | `MIN_DT_S=0.02`; no speed below it, teleport still checked |
| aliasing | **33–67 u/s while merely walking** — the stream is ~20/s but the client's position changes on its own tick | `SPEED_WINDOW_S=0.5`; speed is distance over ≥0.5 s |

### 3. Detect desync

`DesyncTracker` compares the client's reported position against the position the server believes (the
spawn override if set, otherwise the captured spawn value). Live:

| condition | result |
| --- | --- |
| at rest | **0 reports**, `max_deviation_u 4.031` — the measured instrument offset, so the threshold does **not** fire on it |
| after a 19 u walk | **0 reports**, `max_deviation_u 19.007` |
| after walking past the threshold | **143 reports**, `max_deviation_u 28.057` |

The threshold is 25 u because the two positions are **different measurements** with a measured 2–3.7 u
offset that **varies between sessions**; `max_deviation_u` is logged every 30 s so a tighter number can
be chosen from data.

### 4. Why CORRECT is not implemented — four measurements, do not re-litigate

| attempt | result |
| --- | --- |
| full 48-fragment spawn record, position changed | accepted, ignored — 577 samples |
| minimal 1-fragment bundle (position fragment only) | accepted, ignored — 358 samples |
| **delta-shaped 9-fragment record**, with the player **23 u then 55 u DESYNCED** | accepted, ignored — 266 sends |
| `ReceivePlayerPositionClientMsg` → `IPositionReceiver` | the method is `0x140294860` = **`ret 0`** (vtable `0x1482eb160` slot `+0x40`) |

The third one is the important method point: **testing at rest cannot distinguish "applied" from
"ignored"** when the server asserts the value the client already has, so the player was walked away
first. And the capture explains the whole thing — the local player's position is replicated state sent
**only when it changes** (the spawn copies carry 7 position pairs, every delta copy carries none), so
there is no example of a server correction anywhere in the record.

**ALC means what it says: the client is authoritative over its own position, and the server reads,
validates and escalates.** A deployment that wants enforcement uses the verdicts (kick, re-send the
spawn record, flag for review); it cannot move the player.

## Two bugs found on the way, both now covered

1. **`round(None)` in the channel-1 hot path dropped every session** ~24 s after spawn. `last_speed` is
   `None` until the second sample; the `TypeError` escaped `on_app_data`, the feed-error handler
   **dropped the peer**, and the client reported `transportError 4` + `Disconnected from REP`. Found by
   an A/B with the feature off (which survived) plus the server's own `feed-error` traceback naming the
   line. **All 209 parser-level tests were green while every session died** — the parser was fine, the
   WIRING was broken. Fix: read through a local (`validator = self.movement`) because the block can set
   `self.movement = None`, and normalise before the log call.

2. **The delta record's boundaries are not identical across captured copies.** seq `0x73`'s payload is
   7153 and `0x98`'s is 7154, because the position fragment is 48 bytes in one and 49 in the other — so
   one boundary set describes most copies and slices `0x73` **one byte late, silently dropping a
   fragment's leading key byte**. A parse→encode round-trip **cannot** detect that (it is the identity
   for any bytes); comparing the decoded **(key, type)** tuples can, because the key→type binding is
   1:1 and measured. The composer now refuses, and the arming code tries each copy and keeps the first
   that composes (it chose `0x98` of 5).

## Caveats, stated rather than hidden

- `SETTLE_S=60` means speed is **not** validated in the first minute of a session (the load transition
  is measured at 40–73 u/s for ~57 s). Desync detection is unaffected — it works from the first sample.
  It should become a real "loading finished" signal instead of a timer.
- The desync threshold **cannot be tight yet** for the reason above (a session-varying 2–3.7 u offset).

## Validation

229 world tests OK (10 in `test_movement.py`, 8 in `test_alc.py`, 4 for the delta composer in
`test_rep.py`), 24 gateway OK, 12 Rust OK, `gen-protocol-fixture.py --check` OK, all five RE tool
self-checks OK. Live: 0 transportError, 0 disconnects, 0 timeouts, 0 unmarshal errors, 0 `feed-error`,
cable absent.

## Files

`services/world/src/azoth_world/javelin/alc.py`, `services/world/src/azoth_world/movement.py`,
`services/world/src/azoth_world/rep.py`, `services/world/tests/test_{alc,movement,rep}.py`,
`services/world/src/azoth_world/javelin/__init__.py`.
