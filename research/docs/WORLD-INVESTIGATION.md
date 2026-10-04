# World entry investigation — snapshot 2026-10-02

The current frontier is movement, attack, inventory, and the in-game activity timer.
Read [`../../STATUS.md`](../../STATUS.md) (2026-10-03 handoff) and
`research/derived/symbols.json` key `gametransform_attach_ab` before this file.
The sections below record the possession fix. They are not the next experiment.

This is the detailed evidence snapshot extracted from the project dashboard.
For the current short frontier see [`../../STATUS.md`](../../STATUS.md); for the
repeatable attempt checklist see [`WORLD-DEBUGGING.md`](WORLD-DEBUGGING.md).

> Full historical sessions: `docs/sessions/` (start at `2026-09-13_pre-monorepo-STATUS.md`, Spanish archive).
> RE findings: `research/atlas/` (endpoints, models, errors, levers, observed traffic + OpenAPI).
> A new finding goes to the atlas, not here.

## RESOLVED 2026-10-02: the world renders and the local player is possessed

The black-`InGame` blocker is **solved**. Fresh PID 25952 / REP session 232 rendered
`NewWorld_VitaeEterna` with the local player in it. The cause was one redacted identity
in the replayed capture and the fix is one targeted substitution:
**`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`**
(`javelin/replay_store.py::fill_local_player_uuid`). See the table and the new frontier
right below, and `research/atlas/levers.md` for the lever entry.

## Where we are (2026-10-02)

- **SOLVED: the world renders and the local player is possessed (2026-10-02, fresh PID 25952 /
  REP session 232).** The whole "black InGame" chain terminated at one redacted identity in the
  replay. The local-player gate compares the UUID carried by a `PlayerComponentClientFacet` record
  against the character UUID in the client's local option store; in the capture **every player's
  facet carries that UUID in clear text except the capture author's own, which is redacted to
  zeros** — and that record is the one that must be ours. The slot is unambiguous: a redacted
  16-byte span immediately followed by that record's length-prefixed display name
  (`<16 zero bytes> <len> <name>`; in the 46 KB bundles the other two 16-byte spans are followed by
  `0x18`/non-printable bytes instead). Fix: `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`
  (`javelin/replay_store.py::fill_local_player_uuid`). Measured effect, same probe, same code path:

  | Signal | Before (session 222) | After (session 232) |
  | --- | --- | --- |
  | `writerStatus1` / `writerStatus2` | 0 / 26 | 2 / 24 |
  | `managerSetContext` | 0 | 2 |
  | manager `+0x08` / `+0x10` | `0x0` / `0x0` | `0x20e4df0a800` / `0x20cd63a8eb9` |
  | record-1 slot `state+0x618` | null | non-null |
  | portrayal-table inserts | 148 | 226 |

  Evidence: `research/sessions/world_20261002T065937Z_pid25952_session232/`; the before-run is
  `research/sessions/world_20261001T212843Z_pid28656_session222/`.
- **NEW FRONTIER (what is still missing, all measured 2026-10-02 on session 232):**
  1. **No movement.** The client emits a constant ~21 messages/s regardless of input (measured
     over 45 s: 105/105/105 idle vs 104/106/105/105 with WASD held), and the game window **does**
     have keyboard focus (`GetForegroundWindow` = `New World`, pid 25952). So input reaches the
     client and produces no state change: the player is a replica the client renders, with no
     input-driven local controller bound.
  2. **No inventory.** 23 `RMIDispatch` errors, all
     `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`: the replay addresses storage
     facets that do not exist locally.
  3. **26 `slices/remoteplayer.dynamicslice` warnings** ("Couldn't get Transform component on the
     slice!") — the other players' actors, not the local one.
  4. **`State(InGame) is timeout` still fires every 30 s**; `scripts/patch-timeout-watchdog.py`
     patches a different site than the one reporting.
- **The GATE MECHANISM chain, confirmed by measurement (2026-10-01/02).** `FUN_146929DF0` writes
  gate status `state+0x318`. It first looks up a value in a **thread-local** option store
  (`FUN_140FCA4E0` over `FUN_141027E40`); no entry → status 2 with no comparison at all. With an
  entry it compares (size, then `memcmp`) that value with `entity+0x7d0`; equal → status 1. Two
  empty strings compare equal, so the requirement is "the store has an entry", not "both sides are
  non-empty". Measured on the before-run: 26 writer calls, **26 local lookups hit**, 26 status 2 —
  i.e. the store side was fine and the compared value was the zero-filled (redacted) wire UUID.
  On status 1 the gate `FUN_146764CD0` sets latch `+0x31d=1` and calls two setters:
  `FUN_141025F70()` vtable `+0x20` with `FUN_1416BC930(state)+0x20`, and the manager
  `FUN_141026080()` vtable `+0x10` (the context setter) with `FUN_1406C6A00(state)`. Its only
  caller `FUN_14683C8D0` (facet vtable `0x148535728` slot `+0xb0`) fires the writer when
  `*(entity+0x7c0)->vtable[0x60]()` or `*(entity+0x870)->vtable[0x60]()` reports a value, passing
  `entity+0x7d0` (the wire UUID) and `entity+0x880` (the display name). Pseudocode:
  `research/derived/decomp/gate-chain.c`; landmarks in `research/derived/symbols.json`.
- **FIELD SHAPE confirmed on the wire (2026-10-02).** In each player's facet record the UUID is
  immediately followed by `[u8 len][name]`: other players show
  `45 29 88 c6 … 45 e6 | 07 | "Unusual"`, the local player shows
  `<16 zero bytes> | 0a | "Mixed Nuts"`. The same UUID also appears in clear text in the
  smaller per-player bundles (seqs `0x77/0x79/0x7b/0x80/0x84` and their repeats), which is how the
  slot was identified.

- **GATE MECHANISM SOLVED (static + live, 2026-09-30 evening).** The manager-context setter
  `FUN_146928D80` runs only when gate `FUN_146764CD0` sees status `+0x318 == 1`. The ONLY writer
  of `+0x318` is `FUN_146929DF0`, called once from `FUN_14683C8D0` (slot `+0xb0` of the
  `PlayerComponentClientFacet` vtable `0x148535728`): it compares the facet's option string at
  `entity+0x7d0` (slot `+0x7c0`, presence byte at `+0xa0`) against the client's local option store
  (`FUN_140FCA4E0` over the `FUN_141027E40` container, thunk `0x1405717F0`). Status becomes 1 only
  on an exact string match with BOTH sides non-empty; otherwise 2. Gate requires additionally
  `+0x31c != 0` (ctor default `0x1000000` — already satisfied) and one-shot latch `+0x31d == 0`.
  The facet entity is a 0xb20-byte pool object allocated by name
  (`'PlayerComponentClientFacet'`, alloc site `FUN_1467C7140`, ctor `0x146711870`).
  Evidence chain: `research/sessions/world_20260930T143111Z_pid39172_session1059/`
  (`gate-live-probe.jsonl`: lambda flag 0/expected empty; `gate-slots-probe.jsonl` +
  `final-slots.jsonl`: slot `+0x7c0` marker was -1 during the burst, initialized to 0 after,
  presence NEVER non-zero; the compared string never lands). **The single missing wire artifact
  is the option-presence flag + string** — candidates: a later record of seq `0x25` (records
  2–94) or a fragment of `0x29`/`0x2a`. Next A/B: inject a shaped option fragment into record 1
  and watch `[slot+0xa0]` + gate status.
- **GATE MECHANISM RE-READ FROM PSEUDOCODE (2026-10-01, corpus complete).** The full-client
  decompilation finished (`%LOCALAPPDATA%\Azoth\decomp\corpus\8654f01d324636d9`, `status=complete`,
  423579 functions), so this chain is now read instead of inferred. Corrections to the bullet above:
  (1) `FUN_146929DF0` writes `+0x318` in two steps — if the local option lookup
  `FUN_140FCA4E0(out, key)` reports "no value", status is 2 **without ever comparing the wire
  string**; only when the lookup has a value does it compare (size, then `memcmp`) that value with
  `entity+0x7d0`. (2) Two empty strings compare **equal**, so the requirement is not "both sides
  non-empty" but "the local store has an entry". (3) The store is **thread-local**, not a global
  options document (`FUN_141027E40`, TLS slot `_DAT_14e85384`, vtable `0x147f20210`, provider list at
  `+0x20`, value map at `+0x58`). (4) On status 1 the gate `FUN_146764CD0` sets latch `+0x31d=1` and
  calls **two** setters: `FUN_141025F70()` vtable `+0x20` with `FUN_1416BC930(state)+0x20`, and the
  manager `FUN_141026080()` vtable `+0x10` (context setter) with `FUN_1406C6A00(state)`; on status
  != 1 it skips both and only raises event `UNK_1468918C0`. (5) The writer's only caller
  `FUN_14683C8D0` (facet vtable `0x148535728` slot `+0xb0`) fires it only when
  `*(entity+0x7c0)->vtable[0x60]()` or `*(entity+0x870)->vtable[0x60]()` reports a present value, and
  passes `entity+0x7d0` (wire string) and `entity+0x880` (value applied on success). The pseudocode
  is cached at `research/derived/decomp/gate-chain.c` and the landmarks are in
  `research/derived/symbols.json` (`local_option_gate_status_writer`, `local_option_lookup`,
  `local_option_store_thread_local`, `facet_option_apply_from_entity`). **Consequence for the next
  measurement: the 39 status-2 dispatches are ambiguous — they may be the "local store has no
  entry" path rather than a wire-string mismatch. Watch the two arms of `FUN_146929DF0`
  separately.**
- **True AZ wire VLQ (settles the `8e 4c` question).** `FUN_14087B5C0`: `b0<0x80: v=b0`;
  `0x80..0xBF: v=((b0>>1)&0x3f)<<7 | (b1&0x7f)` — the follow byte is the HIGH part
  (`8e 4c -> 972` verified). `0xC0..0xDF: v=((b2<<8|b1)<<5)|(b0&0x1f)`;
  `0xE0..0xEF: v=((b3<<16|b2<<8|b1)<<4)|(b0&0x0f)`; `>=0xF0`: 4 LE bytes bswapped `<<3|(b0&0x07)`.
  The Ghidra pseudo-C misleads (reads LE); trust the asm shift/OR chain. With it, seq `0x25`
  record 1 parses cleanly: 48 fragments, frag 0 = key `0x47` type 972
  (`DE1A18A9-CE9E-4336-8DF8-698A73C579D4`), all type indices resolve in the installed 1.400
  `typeindex.json`. Wire strings are LENGTH-FROM-STRUCT (`FUN_140876D80` reads count from
  `[struct+0x50]`, preset 0), not length-prefixed.
- **Type-972 descriptor vtable `0x14801B088` fully mapped**: `+0x48` = field walker
  `FUN_14150D590` (struct `+0x8` u32, `+0xc/+0x1c/+0x2c` u16, `+0x40` string, `+0x68` GUID,
  `+0xa8` u8, `+0xb0/+0xc0` u32), `+0x50` = entity ctor `FUN_14150D7C0`, `+0x00` allocates a
  holder for the option family `crossplay-off-bypass`, `test-non-permanent-ownership`,
  `maintenance-mode-bypass`, `impersonate-others`, `create-character-*-bypass`,
  `use-player-bot-slice-for-new-characters` (names at `0x147F46800`). Frag-0 walker-ordered
  values: `u32=3`, `u16=1,0,0`, GUID 16 B, `u8=0x5A`, `u8=0` — small enums, no string.
- **Latest fresh run PID 39172 / REP session 1059 (2026-09-30 14:29Z) reached `InGame`, loaded
  `NewWorld_VitaeEterna`, drained 26 queued messages, and initialized `GDERenderManager`; the frame
  stayed black and `State(InGame) is timeout` appeared at 14:30:42Z.** Full local evidence is under
  `research/sessions/world_20260930T143111Z_pid39172_session1059/`.
- **Changes that enabled stable `InGame`** (measured live):
  1. `scripts/patch-predicate-flag.py` — `LoadContextAndLevel` hands the virtual predicate's result
     to `ClientContext::Initialize` as its 7th argument, and `Initialize` **self-cleans when that
     value is 0** (`14171ba31 cmp byte [rsp+0x110],0 / jne skip / call 0x1416835B0`). The predicate
     returns 0, so the context died in the same millisecond. The archived `patch-context-gate.py`
     forced `31DB90` (`xor ebx,ebx`) — **exactly the value that triggers the cleanup**. Corrected to
     `B30190` (`mov bl,1`) + NOP the `jne` at `0x146448F72`.
  2. `AZOTH_REPLAY_SPLIT_SEQ=0x25` + `AZOTH_REPLAY_SPLIT_DELAY_S=10` — the 46 KB local-player bundle
     used to arrive 17 ms after `Initialize`, before the level existed, and was dropped. Only 1
     bundle is skipped now; the other 26 are queued and replayed once the context is up.
  3. `rep.py` post-replay heartbeat (type `0x15d`, RELIABLE flags `0x21` since 2026-09-30 —
     the old unreliable `0x20` form was ACKed at Carrier level but never processed: 0 pongs in
     949k traffic lines; now 200/200 pongs match our ticks) + `scripts/patch-timeout-watchdog.py` —
     the official server pinged `0x15d` every ~1 s and the client echoed it; the capture ends, the
     server went quiet, and the per-state watchdog (`FUN_146445E10`) forced
     `connection_ingame_timeout`. The heartbeat continues the exchange (stretched the window
     44 s → 58 s) and the watchdog patch (`0x146445EFB B001→B000`) stops it from reporting a timeout.
     The heartbeat keeps the connection exchange alive; it does not by itself advance
     replica processing or create/possess the local player.
  4. `rep.py` DTLS **stale-session reset** — see "The REP flakiness was a server bug" below. Without
     it, most world attempts never got past `WaitingForREPConnection`.
  5. `rep.py` suppresses the duplicate LevelInfo (type `0x663`) at replay seq `0x4d`
     (2026-09-30, behind `AZOTH_REPLAY_SEND_DUP_LEVELINFO=1`). The second `LevelInfoChanged`
     (~15 s after the first) swaps the context the message port reads: `clientContext == nullptr`
     on every bundle after it, with no `Cleanup()` in the log. With the dup suppressed the context
     stays alive — but the bundle pipeline stays dead anyway (next row).
- **The world renders black because the local player is never possessed (not a camera problem).**
  Measured live 2026-09-30 (fresh processes, all day): the manager table holds 13 real actors
  (vtable `nw+8033f90`, standing at 9345-9354, 2721-2756, 83-88) + stub id `13`. Writing camera
  positions (`+0x54/+0x64/+0x74`, world-scale `+0xc8/+0xcc/+0xd0`), orbiting 6 offsets, freezing
  the view matrix — none of it draws anything: the matrix at `FUN_145f62e80+0x90` and the camera
  source floats (`+0x78=1.309, +0x84=1.778, +0xb8=0.2, +0xd0=1024.0`) sit at frozen defaults.
  The client sends ONLY `0x15d` pongs on W (1503x); the official client drives the world
  (`0x102e/0x102f/0x192c/0x101d/0xf7f/0x66b/0x143d/0x1a59/0x12f6/0x635/0x5b2`). No player
  controller exists client-side. `[mgr+8]` is an object pointer consumed by the manager's asker (the
  per-frame asker `FUN_141042820`, sole gate caller, uses it directly as `rdi+0x38/+0x80` and
  calls `[rdi+0x98]->+0xd8`), not a table key — stuffing a node id there interprets the id as
  a pointer (luck-dependent crash/limp). `FUN_146801040` (table lookup, slot `+0x78`) is never
  called by anyone. Sweeping all 13 ids (`scripts/frida-possess-all.py`) reaches `InGame` but
  stays black. The actor factory `FUN_141563e20` has 1 caller (`0x1416957c0`) with 0 callers.
  The `Received new local player metadata` trace is category 3 and currently
  suppressed; its absence from Game.log is not evidence about that handler.
- **`[obj+0x18] >= 3` is a StateReplication trace level, not the actor constructor.** The block at
  `0x1417182db` formats the log line `Received new local player metadata... newActorId=`. The same
  macro gates every `StateReplication` trace (`edx` 1..4). The live value 2 suppresses categories
  3 and 4. Forcing the branch does not build an actor because that code only emits a trace.
  Do not chase a missing third fragment for this check. The indirect manager setter is now known,
  but the StateBundle condition that should call it remains unknown. Stuffing a world actor into that slot is the wrong shape
  (`FUN_1416af4b0` then reads `holder+0x60` as another holder) and crashed
  `NewWorld.exe.17008.dmp` at `0x146800e47`.
- **~~An indirect manager-context setter is now identified, but it is not reached during replay.~~**
  SOLVED same day — see the gate-mechanism bullet at the top of this section: the string equality
  that decides status 1 vs 2 never succeeds because the option string never arrives on the wire
  (facet slot `+0x7c0` presence stays 0; the lambda/local side is empty too). The
  "fragment or predicate that should activate it" was the option-presence fragment; no ghost
  predicate remains.
- **The deferred-recursion warning has not been shown to cause this view failure.** On PID 45476,
  session 1058, the runtime cvar was set to 16 before entry, yet recursion warnings continued and
  the client still timed out black. PID 39172 used the default cvar and sampled empty queues at
  every drain entry. Session 1059 includes REP data, Game.log, screenshot, and probe logs, but no
  HTTP rows were copied for that launch; it is not HTTP-shape evidence.
- **The replay does place world actors.** Live 2026-09-27 18:28: 13 actors, transform at
  `+0x140`, standing together around (9330, 2750, 85). The interior drew during load, then the
  view cleared. Writing one of those ids into `[mgr+8]` does not attach the camera. Node id 13
  is not an actor. `AZOTH_V3_TRAILER=official` fails registration (`eos_unknown_error`); leave
  the trailer at `00 00 00 00`. The actor copy-constructor is `FUN_14161b570`; `FUN_141563e20`
  skips it when the prototype pointer is null. That is the remaining hole.
- **Carrier delivery is not the current proven blocker for the initial state bundle.** Fresh run
  2026-09-30 13:01Z, PID 54936, REP session 1052,
  build 1.400.6031.6004151, REP session 1047: `scripts/ack-window.py` reports all 43 chunks of
  replay seq `0x25` ACKed, as well as all logged 43- and 91-chunk replay messages. The client
  logs `ProcessPendingReliableMsgQueue processing 26 messages`, initializes `GDERenderManager`,
  then records 25 `RMIDispatch` failures because facet target IDs were not found. It does not log
  `Received new local player metadata`, but that message is behind the category-3 trace threshold
  (`FUN_146165ff0`) and the current level suppresses it; log absence does not prove the handler
  was skipped. The screenshot returns to black with a live FPS overlay.
  This supersedes the earlier interpretation that `0x25` lacked Carrier ACKs and blocked the
  reliable stream. Carrier ACKs prove only transport receipt; they do not prove application
  reassembly, stream-reader consumption, bundle dispatch, or entity creation. Next: establish the
  first missing application boundary (stream reader → bundle split → visitor → actor creation),
  then correlate the missing RMI target IDs to the replay records. Do not change chunk pacing until
  a fresh capture actually shows an ACK gap.
- **The initial visitor burst reaches portrayal/table insertion, but the known actor factory is not
  called.** A read-only burst probe on PID 54936 recorded 214 bundle splits and 214 record-handler
  entries (record IDs 1–94, with repeats), 94 portrayal calls, 116 portrayal-table inserts, and
  zero calls to `FUN_141563e20`. The earlier probe on PID 45592 had 283/283/94/148; its record map
  was empty because `NativePointer.toNumber()` is not supported. Decompilation corrected an earlier
  label: `FUN_14178ec80` removes/destroys a portrayal; it is not actor creation, so its zero count
  says nothing about spawn. The current probe fixes the record ID read and correlates
  portrayal/insertion/factory calls with each record. The complete ignored evidence
  bundle (Game.log, REP session, gateway HTTP rows and exact body sidecars, ACK analysis, probe log,
  screenshot, and hashes) is `research/sessions/world_20260930T131622Z_pid54936_session1052/`.
- **Fresh reproduction: all outbound transport is ACKed, but there is still no possessed player.**
  2026-09-30 13:36Z, PID 35508, REP session 1055, build 1.400.6031.6004151. A 13:41Z snapshot
  still shows a black frame at 30 FPS. Game.log shows the 26-message drain and
  `GDERenderManager Init()`, then repeated `Exceeded max recursion for deferred actions`, followed
  by periodic connection timeouts and local network warnings. The REP snapshot has 18,220 events;
  all 1,338 outbound Carrier sequences were ACKed, including
  every fragment of the initial 46 KB and 99 KB messages. The burst probe observed 283 bundle
  splits/visitor calls across record IDs 1–94, 94 portrayals, 148 table inserts, and zero calls to
  the known factory `FUN_141563e20`. A read-only getter snapshot at 13:38Z returned null for both
  the local-player entity slot and readiness pointer. Evidence is in
  `research/sessions/world_20260930T134112Z_pid35508_session1055/`.
  This closes the missing-Carrier-ACK hypothesis for this run and repeats the no-holder observation
  on a fresh process. The zero factory count is not proof that no other creation path exists. Next,
  connect the record-1 handler's fields to the manager dispatch gate and exact replay payload
  records before changing replay data.
- **Fresh instrumented reproduction: record-1 metadata exists, possession does not.** PID 39284,
  REP session 1057, fresh `NewWorld.exe` 1.400.6031.6004151. All three read-only probes were
  attached before the user-interface transition. Game.log confirms `NewWorld_VitaeEterna`,
  `ProcessPendingReliableMsgQueue processing 26 messages`, and `GDERenderManager Init()`; the
  captured frame is still black. The record-1 handler ran 30 times. At its first measured call,
  `state+0x618` changed from `{entity=0, metadata=0}` to two non-null pointers, then changed again
  on later record-1 calls. Throughout those calls manager `+0x08` and `+0x10` remained null. The
  burst totals match the prior clean run (283 splits/visits, 94 portrayals, 148 table inserts, zero
  calls to known factory `FUN_141563e20`). Thus the local-player metadata slot is populated, but it
  is not the possessed-holder object and does not create the visible player. The ignored evidence
  bundle is `research/sessions/world_20260930T140348Z_pid39284_session1057/`.
- The same run logged repeated deferred-action recursion warnings. The cvar global at
  `0x14a321a4c` read as 0 (effective batch limit 1); the read-only probe sampled both queues empty
  at every drain entry during the black frame and saw no target-lookup calls. This does not exclude
  a short queue during the earlier warning frames, but it means the warning is not evidence that a
  queue remains continuously populated. A value-16 one-run experiment on PID 45476/session 1058
  still emitted warnings and stayed black; changing the cap alone does not fix the view.
- Session 1057 has no captured gateway request rows: its gateway process had traffic capture
  disabled. The gateway hot-reload supervisor was restarted with `AZOTH_NO_TRAFFIC` cleared after
  the snapshot; verify an append before the next measured entry. Do not treat this session as full
  HTTP evidence.
- **The recursion log is a queue budget warning, not a root-cause label.** Its sole string xref is
  `FUN_1416adce0`. That routine drains the deferred-action queue at `object+0x1b8` in batches, up to
  `max(1, _DAT_14a321a4c)` per call; if entries remain, it logs their count and clears the queue.
  This locates the stage where work is dropped but does not identify which action keeps enqueueing
  or whether that action causes the black view. Decompilation: ignored
  `research/derived/decomp/deferred-action-limit.c`; landmark:
  `research/derived/symbols.json:deferred_action_queue_drain`.
- **HTTP capture was incomplete for session 1054, then restored for 1055.** The game had established connections to local
  Caddy, but `services/gateway/traffic.jsonl` had not appended since 13:00:52Z; the run bundle
  therefore has zero gateway rows and no exact HTTP body sidecars. The REP, game log, screenshot,
  and client probes for 1054 are complete. Restarting the gateway restored appends; a request
  through Caddy returned 200 and was recorded with `Via: 1.1 Caddy`. Session 1055 now has 45
  gateway rows and 51 exact body sidecars. `capture-notes.md` in each run bundle records its
  capture coverage.
- **The initial bundle chunks are all Carrier-ACKed, then the client disconnects before later replay
  traffic finishes.** For session 1052, seq `0x25` ACKed 43/43 chunks and `0x29` ACKed 91/91. Later
  rows after the disconnect have missing ACKs (`0x94` onward); they are a consequence of the short
  session, not evidence that the initial local-player bundle stalled in transport. The session
  captured full encrypted datagrams in both directions and full server plaintext app payloads with
  `AZOTH_LOG_RAW=1`.
- **The REP flakiness was a server bug, not the client.** After a world attempt the client reuses its
  source port; the server fed the new ClientHello into the DTLS session it still held for that port,
  the old state machine swallowed it, the handshake never completed and the server logged **nothing**,
  so the client gave up after 15 s with `@mm_csdkerr_connection_failed (0)`. Measured: 12 ClientHello
  retries from `127.0.0.1:27000` with no `dtls-established`, while a freshly started server handshook
  the same client fine. Fixed by `_is_client_hello()` + session reset in `serve_forever`.
- **Secondary symptom: replica target IDs do not resolve.** `[ERROR] RMIDispatch: The facet target ID couldn't be
  found when trying to dispatch the RMI message` ×25 (almost all
  `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`) — the client receives RMIs for
  entities/facets it never created. Dispatcher `FUN_1416bcba0` (the string's xref).
- **EAC was observed active in an earlier private-runtime session** (kernel hook `e9` at
  `LoadContextAndLevel` `0x146448CD0` and at the CSDK reader `0x146b6eb70`). That is not a
  permanent property of every launch. For PID 45592 at 12:44Z, the private-runtime command
  line, stopped `EasyAntiCheat_EOS` service, and module list showed no EAC component. A one-shot
  read-only getter interception then measured `[inner+8] == NULL` and `[inner+0x10] == NULL`; its
  raw snapshot is in the ignored session folder. This confirms no possessed holder at capture
  time, but does not identify which bundle record should create it. Never use Frida,
  ReadProcessMemory, or a debugger while EAC is active; recheck the exact process for every probe.

## METHOD: one A/B = one fresh game process (learned the hard way)

- After a failed world attempt the client **destroys its `ClientContext`** and never re-creates it
  in the same process. Every later attempt logs
  `HandleUnexpectedMessage skipping ReceiveStateBundle ... clientContext == nullptr` for every
  bundle and falls back to the menu. **Restart `NewWorld.exe` for every A/B** or the result is garbage.
- This invalidates every negative measured on a reused process. Re-tested fresh: `0x65c` IDs,
  `interest=91` IDs, 36-byte text UUID remap, broad `mixed` — all still negative.
- The world loads on the first attempt **regardless of the substitution**; the earlier
  "persona loads the world" claim was conflated with the fresh-process effect. The persona rewrite
  is still the safest default (it feeds the live identity) but is not proven to be load-bearing.

## Replay A/B levers (world env, all default off, see `research/atlas/levers.md`)

| Env | What it does |
| --- | --- |
| `AZOTH_REPLAY_SPAN_SUBSTITUTION=character\|session\|persona\|mixed` | fills redacted spans of length 16/18/19/20/36/61 in the replay with live identity values |
| `AZOTH_REPLAY_SPAN_SEQS` / `AZOTH_REPLAY_SPAN_LENGTHS` | scope the substitution (e.g. `0x25,0x29,0x2a` + `16,61`) |
| `AZOTH_REPLAY_SPAN_SUBSTITUTION2` / `_SEQS2` / `_LENGTHS2` | second pass with a different selector (e.g. `session` on `0x6`) |
| `AZOTH_REPLAY_SPLIT_SEQ` / `AZOTH_REPLAY_SPLIT_DELAY_S` | hold everything from `seq >= SPLIT` until the client has loaded the level |
| `AZOTH_REPLAY_FRESH_LEVELINFO=session` | fresh key for the duplicate `0x663` at seq `0x4d` (produces a second `Initialize`) |
| `AZOTH_REPLAY_IDENTITY_REMAP=session\|character` | the six 36-byte dashed-UUID slots only |
| `AZOTH_REPLAY_HEARTBEAT` (default `1`) | continue the captured `0x15d` ping/pong after the replay drains (the real server pinged every ~1 s; without it the client's state watchdog forces `connection_ingame_timeout`). Body `00 01 9d 05 00 03 <tick>` |
| `AZOTH_REPLAY_HEARTBEAT_PERIOD_S` (default `1.0`) | seconds between pings |
| `AZOTH_REPLAY_HEARTBEAT_TICK` / `_TICK_STEP` | starting tick (default the last captured one, `0x6ef8c888af44`) and per-ping increment (default `1e9` = 1 s in ns) |

Validated live on 2026-09-24 (fresh process each): first `Initialize` cleans up; a delayed second
`Initialize` after the map is loaded also cleans up; `0x65c` IDs = session UUID does not change it;
`interest=91` IDs are not the key. See the atlas for the full matrix.

Validated live on 2026-09-27 (fresh process each): with the predicate flag forced to **1** the
`[ClientContext] Initialize()` → `Cleanup()` pair disappears from Game.log, the level loads and the
client reaches `Lumberyard Connection State: "InGame"`; with the split at `0x25` only one bundle is
dropped and 26 are queued; with the heartbeat + watchdog patch the session holds for minutes.
**Do not force the flag to 0** — that is what the archived `patch-context-gate.py` did, and 0 is the
value that makes `Initialize` clean up the context it was just given.

## State-bundle wire (static, build 1.400)

- Type-`0x08` body: `[record_id VLQ][u8 fragment_count]`, then per fragment
  `[fragment_key VLQ][fragment_type_index VLQ][payload]` (`FUN_146af20d0` → `FUN_146af2340`).
- First record of the 46 KB init bundle: **id 1, 48 fragments**; id 1 is the local-player slot in
  `FUN_141717fc0` (`state + 0x608 + id*0x10`; log `Received new local player metadata, updating
  m_localPlayersServerGDERef`). The 13 world actors are other records of the same bundle.
- First fragment: key `0x47`, type index **972** (VLQ `8e 4c`, not `0x8e`=142), GUID
  `DE1A18A9-CE9E-4336-8DF8-698A73C579D4` (old index 144 / typeIndex 972); current getter
  `FUN_1416fcb20`, vtable `0x14801b088`.
- **No type-index shift 1.365 → 1.400:** the installed `typeindex.json` (7052 entries) maps index
  972 / 0x65c / 0x663 / 0x16a0 to the same GUIDs as the 1.365 registry. Do not chase a remap.
- `0x65c` is the **WORLD DATA** blob (first-light codec `world_data_blob_65c.py`, 12706 B) with two
  redacted 16-byte IDs at `+0x05` and `+12690`.

## What NOT to repeat (condensed)

1. **HTTP/1.1 only** — aws-sdk-cpp discards HTTP/1.0 bodies.
2. **getlogininfo is TWO schemas in one body**: lowercase `worlds` (exact reflection keys, extra
   keys DROP the object) + `LoginInfoList` OBJECT with PascalCase `Worlds`/`Characters`.
3. **`Characters: []` empties the panel**; seed a character (canonical: `Azoth` / `11111111-…`).
4. **Queue**: envelope `LoginQueueResponse`, PascalCase, non-empty `Signature`; refresh wants
   `Position: 0` + nested `Token`.
5. **Entitlements** is `{hasMoreResults, lineItems[]}`.
6. Without ETag on CMS the client crashes; credentials `expiration` is a **double epoch**.
7. **Restart the game to re-render** (and now: to get a valid A/B attempt).
8. **Region scope**: scope world lists per region host.
9. **TCP_NODELAY** on responses.
10. first-light VAs are build 1.365 — re-derive with `bytepat.py`; never trust archived displacements.
11. Raw `Cmd_Greetings`, re-sending r2/r4/r5 after replay, 4KB chunk bundling and unprefixed V3
    bodies all failed — do not retry (details in `research/atlas/levers.md`).
12. **Never force the `Initialize` predicate flag to 0** — `cmp byte [rsp+0x110],0 / jne skip` means
    ZERO runs the cleanup path. The archived `patch-context-gate.py` had this inverted; forcing 0
    destroys the context it was meant to protect. Force **1** and NOP the `jne` at `0x146448F72`.
13. **Heartbeat evidence changed on 2026-09-30.** The earlier `0x20` unreliable form
    was Carrier-ACKed but never processed (0 pongs). The current `0x21` reliable form
    produced 200/200 pongs, with heartbeat sequences covered by client CT_ACKS. A prior
    reliable variant caused unbounded retries; do not generalize that result to the
    current sequence/ACK implementation. Follow `rep.py` and the latest `levers.md` entry.
14. **`clientContext == nullptr` on every bundle is a symptom, not the cause.** Before blaming the
    bundle path, check whether `[ClientContext] Cleanup()` follows `Initialize()` in the same ms.
15. **A failed REP handshake is invisible server-side unless `AZOTH_LOG_RAW=1`.** The server logs
    nothing when a ClientHello lands in a stale session, so "packets never arrived" and "DTLS
    rejected them" look identical. Turn the raw log on before theorising about the client.
16. **Do not conclude a Frida hook failed because its counter is 0.** Hook the world attempt's own
    progress first (`ProcessPendingReliableMsgQueue processing 26 messages`): if the attempt never
    happened, every mid-function counter reads 0 and the hook looks broken. This cost several
    cycles before the fix in item 15 made the real cause visible.
17. **Do not force the `[obj+0x18] >= 3` branch.** That compare is the StateReplication trace
    level (`FUN_146165ff0`). The block it guards only formats a log line. NOPing it does not build
    an actor. The camera stays black because `[mgr+8]` is never written.

## Ops / environment notes

- Stack: gateway `:8080`, Caddy `:443`, world `:9000`, hosts private. `python az.py dev` for
  gateway+world (hot reload); launch it detached. `python az.py shot` + `scripts/shrink-image.py`
  for screenshots (never Read the raw PNG).
- Caddy can hang on some hosts after a restart; verify
  `https://d1w0bfy6smo4d1.cloudfront.net/prod/game/getlogininfo/jwt/omni` through `:443` (200)
  before blaming the world server.
- The private runtime copy currently has the DTLS disk patch applied
  (`scripts/patch-dtls-disk.py`, sha256 `537403d4…`); restore it with
  `python scripts/patch-dtls-disk.py restore` when finished. The official Steam exe is untouched.
- EAC restrictions apply whenever EAC is active, including a private runtime. Use static
  analysis and server-side evidence unless a private build without EAC is confirmed.

## Minor debt

- `services/world` needs `pyOpenSSL` (the one deliberate non-stdlib dep — stdlib ssl has no DTLS).
- After a session: `python az.py doc` (regenerate `research/atlas/openapi.json`) and commit the atlas.
