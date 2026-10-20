# 2026-10-18T13:00Z — the flag A/B: correction is refuted in every shape, and a crash bug was fixed

One variable changed from the previous run — the Carrier flag byte — plus the fixes needed to make
the run possible at all.

## The A/B

The decompiled `FUN_14643e7b0` shows the Carrier flag byte selecting between two gates that are not
equivalent:

```
byte[msg+8] == 0  -> reliable path: dispatcher runs, port[0x78] NOT advanced
byte[msg+8] != 0  -> unreliable gate: instance id must match, seq must be > high-water,
                     THEN port[0x78] = seq and the dispatcher runs
```

Every captured state bundle the client applies arrived through the second path (flags `0x20`); this
server had always sent `0x21`. So the correction was sent with **`0x20`**:

```
movement-desync            error 3.202 u, streak 5
movement-correction-queued body_bytes 7254, body_kind "hybrid"
state-stream kind=position flags "0x20"  size 7255
```

Result: **identical to the reliable attempt.** Error grew past the correction to **11.861 u and kept
rising**, with `Failed to unmarshal` **0**, `ValidationError` **0**, `transportError` **0**, and the
character visible.

## Four shapes, all refuted

| shape | size | flags | client errors | character | applied |
| --- | --- | --- | --- | --- | --- |
| full spawn record, looped at 1 Hz | 46 408 B | 0x21 | 0 | **invisible** | no |
| position fragment alone | 102 B | 0x21 | 0 | visible | no |
| the record the client applies + position | 7 255 B | 0x21 | 0 | visible | no |
| **the same, unreliable** | **7 255 B** | **0x20** | **0** | **visible** | **no** |

**Neither composition nor the flag byte is the obstacle.** Correction by sending state bundles is
closed for this build. The remaining question is *why* a record the client parses is not applied —
which happens after `FUN_141717fc0` dispatches, and is not answerable by trying more payloads.

## The bug that was actually breaking sessions

Three consecutive runs failed to reach the world. The server armed the replay and went silent, and
its log ended with:

```
UnboundLocalError: cannot access local variable 'traceback' where it is not associated with a value
```

The cause: a **local `import traceback`** inside the *feed-error* handler. A local import makes the
name local for the **whole function scope**, so the *tick-error* handler — earlier in the same
function — referenced an unassigned local and raised **instead of logging**.

That converted "one bad datagram" into "the world process dies", which is the exact failure both
handlers exist to prevent. It is also a plausible contributor to the intermittent `transportError 4`
sessions recorded earlier in this project: the client sees the connection drop, and the server's own
log ends without an error because the error handler was the thing that crashed.

Fixed by deleting the local import; the module-level one at line 36 is sufficient. With the fix in
place the same handlers log properly and the server survived a full session.

## A bug of mine, caught by the tests

`_send_replay_message` had its **body** edited to read `flags` while its **signature** still said
`(self, server, msg)`. Every replay send raised `NameError: name 'flags' is not defined` inside the
tick loop: 104 tick errors, 46 client re-registrations, never reached the world.

The source-string test I had written passed throughout, because it only looked for the body text. The
fix is a test that inspects the **parameter list**:

```python
params = inspect.signature(rep.PeerSession._send_replay_message).parameters
self.assertIn("flags", params)
```

## What stands

* **Detection works and is verified live**: `movement-ready` at 11.3-14.6 s across five runs, offset
  calibrated `(-2.2002, +3.3777)` with residual 0.0000, desync fires on real divergence.
* **The position fragment is located** from the client (fragment #35, payload `38310..38397`,
  `key=16 type=11`), and a 101-byte bundle can carry it.
* **Correction does not work** in any of the four shapes measured.
* **The world server no longer dies in its own error handler.**

## Files

* `movement-events.jsonl` — the A/B's calibration, desync and correction.
* `position-sends.jsonl` — the 7255-byte send with `flags: 0x20`.
* `Game.log` — the client log: 0 errors of any kind.
