# 2026-10-15 overnight — past the twenty- and thirty-minute thresholds, and the position re-send family closed

Two experiments and one refutation. The refutation is the bigger result.

## 1. Streaming the spawn record does NOT move the player (negative)

### 1a. The full record

The obvious next step after `server_owns_the_player_position_measured_20261014` was: the
position lives in the spawn record, the replay sends it once, so stream it again with a
fresh replication counter and the server's position becomes authoritative over time.

**The wire half works perfectly and the client ignores it.**

| measure | value |
| --- | --- |
| position bundles sent (server) | **75+** (`state-stream kind=position`, size 46408) |
| `state-position-override` events | **99**, each `replacements: 1` |
| positions rotated mid-session | 4, 25 s dwell each, `AZOTH_STATE_POSITION=file:<path>` |
| client samples at 0.25 s | **577** over 145 s |
| client position across all four writes | **(9343.6416, 2786.7327, 87.538)** — never moved |
| `Failed to unmarshal` / `ValidationError` / `transportError` | **0 / 0 / 0** |

The client parses and accepts the re-sent spawn record and does not apply its position.
**The spawn record is consumed once at spawn.**

**Where the position is instead.** The player's x,y is persistent replicated state on the
entity: after W moved the player to `(9353.7227, 2766.062)` the accessor reported exactly
that at the start of the next phase. The streamed 7154-byte record-1 bundles do **not**
contain the capture's position pair at all (`CAPTURED_PLAYER_POSITION` is absent from seq
`0x98` in every encoding tried: f32/f64 both endians, scaled i16/i32/i64 at
x1/x10/x100/x1000/x1024), so they do not overwrite it either. That matches the committed
A/B: the state stream is a **prerequisite** for the client simulating the player, not the
carrier of the position.

**Kept in the tree, off by default.** `AZOTH_STATE_POSITION_STREAM=0`. The capability is
proven at the wire level and is needed to test any future position field; it must not be
adopted as a fix. `AZOTH_STATE_POSITION` now also accepts `file:<path>`, re-read on
**every** send, which is what made a mid-session change possible without a restart.

### 1b. The minimal bundle — the family is CLOSED

The full-record negative left two confounds: the client might treat a 48-fragment record-1
bundle as a re-initialisation, and the fragment that carries the position was only a
candidate boundary (a 2-byte pattern). Both are now removed.

**The spawn record's 48 fragment boundaries, measured from the client**
(`frida-record-boundaries`, attached at character select, `tiles: True`, record length 46393):

```text
[2, 25, 171, 280, 320, 6233, 6247, 6275, 6285, 11039, 11086, 11101, 11633, 11650, 11663,
 11678, 11747, 11838, 11859, 11865, 12518, 12531, 29707, 29747, 31129, 31158, 31179,
 31238, 31294, 31307, 33357, 33386, 33395, 33404, 33467, 38310, 38397, 38403, 38416,
 39405, 39415, 41210, 41231, 42228, 44255, 45760, 46286, 46304]
```

The position pair at payload offset 38332 is inside the fragment **38310..38397** — 87 bytes, a
2-byte header `10 0b` (`key=16`, `type_index=11`) plus an 85-byte payload, position at payload
offset **20**. That confirms the boundary the earlier reading doubted and refutes the
alternative that put the next fragment at 39415.

The server then composed a **minimal record-1 bundle carrying only that fragment**
(`compose_position_fragment_bundle`, 101 bytes, asserted to reproduce the captured fragment
verbatim when no override is set, and failing closed if the body stops matching the layout):

| measure | value |
| --- | --- |
| sends | **540** over ~2 min, three positions rotated mid-session |
| wire proof | outbound datagrams decoded: `key=16, type=11` carried `(9300.0, 2750.0)` |
| client samples | **358** |
| client position | **(9343.6416, 2786.7327, 87.538)** — never moved |
| errors | 0 unmarshal, 0 validation, 0 transport, 0 disconnects |

**So the reason is not the fragment count, the bundle size, the record id, the replication
counter or the value's encoding. The client consumes the position once, at spawn.** Do not try
this family again. The lever is `AZOTH_STATE_POSITION_FRAGMENT` (default 0).

**Two corrections to the committed fragment model** fell out of the boundaries: the same
`(key=16, type=11)` pair carries an **85-byte** payload in the spawn record and a **48-byte**
payload in the streamed record-1 bundles, so "a fragment's payload length is implied by the
type" means "the type's reader knows how to consume it", not "the length is fixed"; and the
spawn record is **not** a superset of the record-1 delta (the delta has keys 73 and 72 that the
spawn record lacks, while the 7 shared keys carry identical types).

**What remains.** The position **input** consumer: `ReceivePlayerPositionClientMsg` (wire
4216) delivered to `IPositionReceiver`. Its delivery `FUN_143f97bf0` was decompiled here — it
looks the target up with `FUN_1416bcba0`, calls `target->vtable[0x20](target,
FUN_143fb2b90())` (QueryInterface with the IPositionReceiver GUID) and only calls
`receiver->vtable[0x40](receiver, msg+0x40, msg+0x30)` if that answers. **It never creates the
receiver**, so no target id can work until something binds an instance.

## 2. The 20-minute threshold is passed, for the first time

**The delegate has TWO sites and only one was patched.** A session that spawned at
`22:33:10.804` fired it at `22:53:11.188` — exactly **20 min 0.384 s** — and Game.log
showed:

| marker | count |
| --- | --- |
| `CGame::ActorContainerDisconnect` | 1 |
| `Disconnected from REP` | 1 |
| `exiting to main menu` | **0** |
| `Cleanup()` | **0** |

So `patch-exit-to-menu.py` did exactly what it says (the exit virtual at `0x14100425F` was
skipped) and the session still died: the `call CGame::ActorContainerDisconnect` at
`0x141004230` runs **before** the patched call and tears REP down by itself. The client
keeps rendering its last frame, which is the frozen world plus the red cable the user sees.

Both sites are now NOPed:

```
14100425F  ff 90 d8 01 00 00   call [rax+0x1d8] (exit to main menu)  -> NOP x6
141004230  e8 db c3 41 05      call CGame::ActorContainerDisconnect   -> NOP x5
```

**Result, live, run spawned `23:13:25.170`:** the session had **0** `ActorContainerDisconnect`, 0
`Disconnected from REP`, 0 `exiting to main menu`, 0 `Cleanup()`, 0 `transportError` and 0
`OnLocalNetworkConnectionWarning` for its whole life, and it was still interactive when it ended —
a probe attached at 23 minutes measured W moving the player ~13 u forward and S ~9 u back, the world
server was still emitting on its own clock, and a screenshot shows the world rendered with **no
cable icon**.

| measure | value |
| --- | --- |
| session lifetime | **24 min 8 s** (spawn `23:13:25.170` → last `Game.log` line `23:37:33.227`) |
| how it ended | **killed by our own probe** — `frida-player-position` calls `device.kill` on exit by default; the Windows Application log has **no** faulting event for NewWorld.exe |

**What that does and does not establish.** The 20- and 30-minute thresholds this project has been
stuck at are crossed. **The 2-hour soak is unmeasured**, and every soak must be probe-free.

**A second, probe-free run reproduced it: 24.5 minutes, 0 of every marker** — and it too was ended by
our own instrumentation, this time by a deliberate probe attach for a tool self-test, which faulted
`NewWorld.exe` with `0xc0000005` in an `unknown` module at `0x1a3b65e0051` (the documented Frida
execute-after-unload signature). Two independent sessions crossed 20 minutes and neither was ended by
the client.

**A third run, fully probe-free, then passed 30 minutes.** Spawn `01:03:30`; at **31.9 minutes** it
had 0 `ActorContainerDisconnect`, 0 `Disconnected from REP`, 0 `exiting to main menu`, 0 `Cleanup()`,
0 `transportError` and 0 `OnLocalNetworkConnectionWarning`, and was still running toward the 2-hour
soak. So the 20- and 30-minute thresholds are crossed; **the 2-hour soak is the remaining gate.**

**Method trap, learned the hard way and worth repeating:** the first reading of this run claimed
"past 30 minutes" because the soak watcher only counts markers in `Game.log`, and those counts
simply **stop changing** when the client is gone — a watcher that cannot tell the difference between
"clean" and "dead" is not a soak instrument. It now records the client's PID. Related:
`--keep-process` avoids a probe's *deliberate* kill but not the detach fault.

**Why the arm was not targeted.** The runbook's conclusion ("to keep a session past 20
minutes the ARM must be prevented") is right, but the delegate's function pointer has **no
static reference anywhere in the image** — `0x141004100` has 0 `E8` callers, 0 `lea` xrefs
and 0 qword literals — so the enqueue site builds it dynamically and could not be located.
Neutralizing the delegate's two observable effects is the practical equivalent, and it is
measured. This is a private-runtime sandbox affordance, not a protocol fix: the proper fix
is still to satisfy whatever the server must send to keep the session alive.

## 3. Movement and the cable re-verified on the current defaults

Probe attached mid-session, each key held 5 s with a 4 s gap:

| key | net displacement |
| --- | --- |
| W | 22.998 u |
| S | 19.679 u |
| A | 4.533 u |
| D | 9.360 u |

The same four magnitudes as the committed 2026-10-13 measurement, from the same start point
`(9343.6416, 2786.7327, 87.538)`. The raw samples show a continuous smooth trajectory with a
deceleration tail after each release and a full stop in the gaps. `watch-indicator.py`
classified the cable **absent** on 9 consecutive samples.

## 4. Two tool defects, both of which read as "the client is broken"

- **`scripts/shot.py` selected the window by TITLE only** and printed `New World window not
  found` while the client was in the world (a probe was reading its position). It now
  prefers `winwindow.find_game_window()` (process-image-name), the finder `private-run.py`
  uses, with the title lookup as a fallback; `PrintWindow` reuses that hwnd.
- **`scripts/watch-indicator.py` used `os.system` with a quoted command line.** `cmd.exe`
  strips the leading/trailing quote of a `/c` command that starts with a quote, so shot.py
  never ran and every sample printed `capture is STALE (shot.py failed)`. It now uses
  `subprocess.run` with a real argv.

Until both were fixed, the only instrument that can see the HUD cable was silently
reporting nothing.

## 5. A new fragment-boundary probe, validated

`reverse/probes/client/frida-record-boundaries.py` answers the same question as
`frida-fragment-grammar.py` — where does each fragment of a record start — but hooks **only** the two
per-record readers and parses the first two prefix varints out of the fragment bytes in JS. The older
probe also hooks `FUN_14087b5c0`, the shared varint reader, which runs for every varint read in the
process; the runbook warns about hot hooks, and the one attempt to use it at character select ended
with the client process gone during the Play click.

It reports, per record, the fragment spans **and the record's own byte length**, plus `tiles` =
(`sum(span) + first_offset == record_length`) — the check an opaque-remainder model can never fail
and a real boundary model can.

**Validated live** against the record-1 bundles the state stream re-sends, which is a real self-test
because their boundaries were already known: **60/60 copies agreed** on boundaries
`[2, 60, 3955, 4295, 4301, 4498, 5335, 5386, 7125]`, keys
`[55, 19, 73, 9, 72, 74, 16, 22, 44]` and types
`[4176, 3133, 5606, 3935, 5485, 5691, 11, 3857, 4236]` — an exact match to the committed values —
and every copy reported `tiles: True` (`span_total 7152 + first_offset 2 == record_length 7154`). It
also has `--record <id>` (the older probe's docstring promised one but never implemented it) and
`--keep-process`.

**Why it matters next:** attaching it at CHARACTER SELECT with `--record 1` gets the SPAWN record's
48 fragment boundaries, which is what identifies which fragment carries the player's position. The
current candidate is the `key=16, type_index=11` header at spawn-payload offset 38310, but the same
pair carries a **49-byte** payload in the record-1 bundles and a **1103-byte** payload in the spawn
record, so the boundary model is not settled — and that discrepancy is exactly what the `tiles` check
would resolve.

## 6. First Rust port step: the protocol crate

`docs/ROADMAP.md` section 4 names the wire codecs as the one genuinely port-ready piece. New
cargo workspace at `server/`:

| file | what |
| --- | --- |
| `crates/protocol/src/varint.rs` | the prefix varint (all five widths, hand-verified capture values) |
| `crates/protocol/src/bundle.rs` | the type-0x08 body: prologue, record sequence, fragment grammar |
| `crates/protocol/tests/parity.rs` | byte-for-byte parity over the captured corpus |
| `crates/protocol/tests/fixtures/state-bundles.txt` | 239 KB, generated, not hand-written |
| `scripts/gen-protocol-fixture.py` | generates the fixture FROM the Python codecs (`--check` for drift) |

Zero dependencies, and a line-oriented text fixture so the Rust side needs no serde. **12
tests pass** (8 unit + 4 parity). The parity test doubles as a regression guard on the
position anchor: `the_spawn_record_still_carries_the_position_at_the_measured_offset` fails
if the capture or the parser changes, instead of the server silently losing its position
authority.

## Validation

186 world tests OK (4 new for the position stream), 24 gateway OK, `cargo test -p
azoth-protocol` 12 OK, all three RE tool self-checks OK.

## Files

- `services/world/src/azoth_world/rep.py` — `STATE_POSITION_STREAM*`, `file:` position spec,
  `_bundle_carries_position`, `state_stream_position*`, third rate in `maybe_state_stream`
- `services/world/tests/test_rep.py` — 4 new tests
- `services/launcher/runtime-tools/patch-exit-to-menu.py` — the second NOP site
- `scripts/shot.py`, `scripts/watch-indicator.py` — the two tool fixes
- `server/`, `scripts/gen-protocol-fixture.py` — the Rust port step
- `.azoth/night/drive-position.py`, `.azoth/night/drive-movement.py` — the run drivers
  (ignored)
