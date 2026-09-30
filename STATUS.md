# Azoth — live state

> Full historical sessions: `docs/sessions/` (start at `2026-09-13_pre-monorepo-STATUS.md`, Spanish archive).
> RE findings: `research/atlas/` (endpoints, models, errors, levers, observed traffic + OpenAPI).
> A new finding goes to the atlas, not here.

## Where we are (2026-09-30)

- **The client is in the world and STAYS there.** After character select → queue → V3 → REP replay
  the client loads `NewWorld_VitaeEterna`, reaches `Lumberyard Connection State: "InGame"`, processes
  the state bundles (`ProcessPendingReliableMsgQueue processing 26 messages`) and holds the session
  for minutes instead of dropping after 44-58 s.
- **Three fixes got it there** (all measured live, none guessed):
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
     NOTE 2026-09-30: the heartbeat exchange works but the client still does not advance past
     `State(InGame) is timeout` — it was a real bug, not the bug.
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
  controller exists client-side. `[mgr+8]` is a POINTER to the possessed holder object (the
  per-frame asker `FUN_141042820`, sole gate caller, uses it directly as `rdi+0x38/+0x80` and
  calls `[rdi+0x98]->+0xd8`), not a table key — stuffing a node id there interprets the id as
  a pointer (luck-dependent crash/limp). `FUN_146801040` (table lookup, slot `+0x78`) is never
  called by anyone. Sweeping all 13 ids (`scripts/frida-possess-all.py`) reaches `InGame` but
  stays black. The actor factory `FUN_141563e20` has 1 caller (`0x1416957c0`) with 0 callers.
  `Received new local player metadata` appears 0 times in every log.
- **`[obj+0x18] >= 3` is a StateReplication trace level, not the actor constructor.** The block at
  `0x1417182db` formats the log line `Received new local player metadata... newActorId=`. The same
  macro gates every `StateReplication` trace (`edx` 1..4). The live value 2 suppresses categories
  3 and 4. Forcing the branch does not build an actor because that code only emits a trace.
  Do not chase a missing third fragment for this check. Next: who writes `[mgr+8]` / `[mgr+0x10]`
  (the possessed-player holder). Stuffing a world actor into that slot is the wrong shape
  (`FUN_1416af4b0` then reads `holder+0x60` as another holder) and crashed
  `NewWorld.exe.17008.dmp` at `0x146800e47`.
- **The replay does place world actors.** Live 2026-09-27 18:28: 13 actors, transform at
  `+0x140`, standing together around (9330, 2750, 85). The interior drew during load, then the
  view cleared. Writing one of those ids into `[mgr+8]` does not attach the camera. Node id 13
  is not an actor. `AZOTH_V3_TRAILER=official` fails registration (`eos_unknown_error`); leave
  the trailer at `00 00 00 00`. The actor copy-constructor is `FUN_14161b570`; `FUN_141563e20`
  skips it when the prototype pointer is null. That is the remaining hole.
- **The bundle pipeline dies after the first 26 (the live frontier).** Measured 2026-09-30 on
  fresh processes: the server sends all 137 replay messages (`replay-complete-quiet`), the client
  processes the first 26 (`ProcessPendingReliableMsgQueue processing 26 messages`, builds the 13
  ambient actors) and then NOTHING — 0 calls to split `FUN_146af20d0`, visitor `FUN_141717fc0`,
  portrayal, insert and create over minutes, even with a live context. The 46 KB init bundle
  (seq `0x25`, 43 chunks) is never fully ACKed (chunk resends at try 1, reassembly stalls), so
  every later message waits behind the hole: head-of-line blocking. The client reconnects every
  ~18 min (`@mm_csdkerr_disconnect (4)`, transport death) and each session replays the same
  shape. Next: why the 46 KB reassembly stalls (pacing? chunk-gap? the duplicate 46407 B
  repeats at `0x2a+` that the client already has?).
- **The REP flakiness was a server bug, not the client.** After a world attempt the client reuses its
  source port; the server fed the new ClientHello into the DTLS session it still held for that port,
  the old state machine swallowed it, the handshake never completed and the server logged **nothing**,
  so the client gave up after 15 s with `@mm_csdkerr_connection_failed (0)`. Measured: 12 ClientHello
  retries from `127.0.0.1:27000` with no `dtls-established`, while a freshly started server handshook
  the same client fine. Fixed by `_is_client_hello()` + session reset in `serve_forever`.
- **Remaining frontier: the replica layer.** `[ERROR] RMIDispatch: The facet target ID couldn't be
  found when trying to dispatch the RMI message` ×25 (almost all
  `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`) — the client receives RMIs for
  entities/facets it never created. Dispatcher `FUN_1416bcba0` (the string's xref).
- **EAC is live in the private runtime** (kernel hook `e9` at `LoadContextAndLevel` `0x146448CD0`
  and at the CSDK reader `0x146b6eb70`). Patches land past those hooks and persist. Never unhook it.

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
13. **Do not send the `0x15d` heartbeat as reliable** — ~1/s of unacked reliable datagrams grew
    `sent_reliable` unbounded and the resend storm starved new DTLS handshakes, producing
    `@mm_csdkerr_connection_failed` on reconnect. It must be flags `0x20` (unreliable).
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
- EAC memory ban is SCOPED: official process = never; our private runtime = allowed (but this
  session deliberately stayed static/server-side).

## Minor debt

- `services/world` needs `pyOpenSSL` (the one deliberate non-stdlib dep — stdlib ssl has no DTLS).
- After a session: `python az.py doc` (regenerate `research/atlas/openapi.json`) and commit the atlas.
