# Private client runbook — cold setup, patch policy, and evidence paths

Operational reference for running the private (no Steam, no EAC) client and
for choosing how to observe or patch it. It records what actually works, what
silently fails, and where each artifact lands. Method rules stay in
[LESSONS.md](LESSONS.md); the wire contract stays in
[REP-PROTOCOL.md](REP-PROTOCOL.md) and [JAVELIN-PROTOCOL.md](JAVELIN-PROTOCOL.md);
the phase-by-phase server obligations are in
[SERVER-CONTRACT.md](SERVER-CONTRACT.md).
Build analyzed: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`.

## Current user-visible state (2026-10-11)

This runbook records historical setup gates; passing them does not mean the
client connection is currently usable. REP transport survived 2 h 06 min with
no `transportError` or REP disconnect, while the real red ALC/HUD icon remained
visible. The ALC door (`+0xAA0`) stayed closed and its input stamp (`+0xAA8`)
stopped updating. A separate ~20-minute return-to-menu path also remains open.
The player entity has `CharacterPhysicsComponent` and `GameRigidBodyComponent`,
but W still produces no movement-family messages. See `STATUS.md` and
`docs/ROADMAP.md` for acceptance criteria and the next experiments.

This file answers one question: **"I asked for a private run and it did not
behave; which layer is lying?"** Read it before touching hosts, certs, patches,
or Frida.

## The recommended configuration (one block)

```powershell
# world-server environment (gates 6, 7, 8) — export BEFORE starting the stack
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'   # the world renders + player possessed
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'           # replays 0x1096/0x1097; NOT an ALC/HUD fix
$env:AZOTH_CHUNK_GAP_MS             = '4'           # measured default; slower 20 ms is not a fix
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'         # no post-spawn resend storm (see gate 8b)
python az.py dev

# once: trust Caddy's CA (gate 2)
python scripts/trust-caddy-ca.py

# per run: DTLS disk patch (gate 4), then drive the whole run (gates 5-8)
python scripts/patch-dtls-disk.py apply
python scripts/private-run.py

# after the run
python scripts/patch-dtls-disk.py restore
```

This procedure has reached `player spawn succeeds` and rendered the world; a
separate measured run maintained REP transport for a long time. It is **not**
evidence that the real HUD warning cleared: direct icon and ALC measurements show it remains red. Treat
transport errors, the ALC/HUD state, the 20-minute exit, and movement as separate
results. Everything below explains historical setup failures and measurements.

## Before the gates: the launcher must start at all

`Start-NwPrivate.ps1` is an **advanced** script (`[CmdletBinding()]`) and used
`$PSScriptRoot` inside a `param()` default. Under **Windows PowerShell 5.1**
that variable is not bound yet while defaults are evaluated, so the script died
with `Cannot bind argument to parameter 'Path' because it is an empty string`
and the client window never appeared. **pwsh 7 binds it, so the same script
works there** — which is why the bug can hide. Both `az.py game` and
`scripts/private-run.py` invoke `powershell.exe`, so the whole documented run
path was dead. Fixed 2026-10-09 by resolving the `$RuntimeRoot` default in the
body, after `param()`. If a run reports `FAIL: window never appeared`, check
this first: run the launcher by hand and read its output.

## The layers, in the order they fail

A private run crosses five independent gates. A failure at any gate looks like
"the client is stuck", so identify the gate before changing anything.

| # | Gate | Working state | Failure signature |
| --- | --- | --- | --- |
| 1 | Host routing | `python az.py mode status` prints `in-sync` | `missing:`/`drift:` line; client reaches real AWS |
| 2 | **Local CA trusted** | Windows trusts Caddy's current root | client stuck at the title gate, **0 gateway rows** |
| 3 | Services | one gateway, one world, one caddy | client answers but state never advances |
| 4 | REP trust | DTLS handshake accepted | `@mm_csdkerr_transport_security_error (2)`, `tlsv1 alert unknown ca` |
| 5 | ClientContext | `Initialize()` without a following `Cleanup()` | world loads, screen stays black, `deferred actions` errors |
| 6 | Local-player possession | `replay_local_player_uuid=character` on the world server | context lives, world loads, screen still black, no player |
| 7 | Captured input-response traffic | optional replay of `0x1096`/`0x1097` | historical timeout symptom may change; the real red ALC/HUD icon remains and its input stamp is stale |
| 8 | Replay pacing | default 4 ms; measure each fresh run | 4/8 ms runs had no transport error in the recorded A/B; 20 ms was slower and risked the watchdog; neither proves ALC or movement |
| 8b | **Resend storm** | `AZOTH_RESEND_INTERVAL_S=1.0` (default 0.3) | `transportError 4` ~38 s after spawn: `OnLocalNetworkConnectionWarning` climbs, then `Unexpected client disconnect! {"transportError":4}` |

## Gate 6 is not optional, and its DEFAULT is the failing value

`python az.py dev` forwards whatever `AZOTH_*` variables the **calling shell**
happens to have (this is the same trap as `AZOTH_LOG_RAW`), so a missing variable
is not an error — it is a silently different experiment. The three below must be
exported in the **same** shell that starts the stack, before `python az.py dev`:

```powershell
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'   # gate 6; default is 'off'
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'
# leave AZOTH_CHUNK_GAP_MS unset (4 ms default) and AZOTH_REPLAY_SPLIT_SEQ unset
python az.py dev
```

**These three are now the whole configuration.** The type-0x08 state stream used to be an opt-in
experiment and is now ON by default, because it is what makes the session correct: it is the local
player's own state record (record id 1) being re-sent that makes the client simulate the player
(movement) and keeps the ALC "last response" stamp young (the HUD cable). Measured 2026-10-13, both
gates met: WASD verified in all four directions with correct geometry, and the cable icon absent, with
a one-variable A/B (stream OFF -> position frozen at `(9343.6416, 2786.7327, 87.538)`, W does nothing,
cable RED). See `MOVEMENT_WORKS_state_stream_enables_player_simulation_20261013` and
`WASD_verified_all_four_directions_20261013`.

**Verify the effective config before interpreting anything.** The world server logs it as the first
event of every session (`event: config`) and the stream logs `event: state-stream-armed` with `count`,
`seqs`, `player_bundles` and the two periods. A stream that arms with `count: 0` is a silent no-op -
that exact bug (an equality against its own sentinel) kept the cable RED while the config event
happily reported `state_stream: true`.

**Measure the cable with `scripts/measure-cable.py`,** not by hand: it locates the game window,
captures the screen, crops to the window's CLIENT rect, classifies with the documented box and saves
the crop. Three separate mistakes were made measuring this icon in one day (whole-desktop capture,
stale capture, trusting the label over the image), and the tool exists to prevent all three.

Measured 2026-10-12, same build and same disk patch, one variable (the env):

| | with the vars | without them |
| --- | --- | --- |
| world renders | **yes**, player possessed | **no**, black frame, no player |
| `Exceeded max recursion for deferred actions` | **0** | **5** |
| `replay-local-player-uuid` spans filled | **25** | 0 |
| client channel-1 records | **1470** | **0** |

So an omitted variable reproduces the Gate 5 symptom set (black screen +
deferred-action errors) **even though the predicate patch is correctly applied**,
and it also kills the client's input stream. Do not read that burst as proof that
the predicate patch failed. Evidence:
`runbook_env_vars_are_mandatory_and_verifiable_20261012`.

**Verify the config before interpreting any client behaviour.** The world server
writes its EFFECTIVE configuration as the first event of every session:

```powershell
python -c "import json;print([json.loads(l[l.find('{'):]) for l in open('.azoth/logs/world.log',encoding='utf-8',errors='replace') if '\"config\"' in l][-1])"
```

Check `replay_local_player_uuid`, `input_response`, `chunk_gap_ms` and
`replay_split_seq`. There is one `config` event **per session**, so an accumulated
`world.log` needs the **last** one — reading the first one gave a wrong diagnosis on
2026-10-12. `.azoth/logs/world.log` accumulates every session ever run (671k lines
here); split on `listening-dtls` or delete it before measuring. Evidence:
`config_event_is_the_effective_config_20261012`.

**A Frida detach can kill the client silently.** `attach → measure → detach` is a
potentially fatal sequence on this build: `frida-agent.dll_unloaded` at offset
`0x9c7e0` (`BEX64`, `c0000005`) has now been reproduced by a second, unrelated probe,
and the client logs **nothing** — no `Cleanup()`, no `exiting to main menu`, no
`Disconnected from REP`. Read the faulting module in Windows Application event 1001
(P4/P7/P8) before reading a session death as client behaviour. Evidence:
`frida_agent_unload_crash_reproduced_20261012`.

## Gate 8g — the warning burst is the REPLAY DURATION (measured 2026-10-10)

`OnLocalNetworkConnectionWarning` is a Game.log REP-watchdog counter, not the
left-center red ALC/HUD cable. The measured 2026-10-10 A/B found this counter
tracks replay duration: the client has not re-stamped its REP activity clock while
the replay is streaming, so the burst lasts as long as the replay. This result does
not explain or clear the separate ALC indicator.

Four paired runs, same build, no Frida attached, one variable at a time
(`scripts/measure-run.py`, raw rows in `.azoth/logs/ab-runs.jsonl`):

| run | `AZOTH_CHUNK_GAP_MS` | activity stream | replay | warnings | transportError |
| --- | --- | --- | --- | --- | --- |
| A2 | 20 | off | 76 s (2155 chunks) | **80** | **1** + `disconnected from REP` |
| B2 | 20 | **on** | 29 s | **82** | 0 |
| C | 8 | off | 15 s | **0** | 0 |
| D | *unset* (default 4) | off | 10 s | **0** | 0 |

One caveat on reading the table: the totals are not effort-matched. A2's replay ran
76 s, so its 80 warnings accumulated over a much longer window — but the burst is not
a slow trickle, it climbs 1 -> 80 within the first ~27 s and then stops. The
defensible statement is therefore the qualitative one: **the burst lasts as long as
the replay**, and a run whose replay is short (<=15 s) has none at all.

Three conclusions:

1. **The type-`0x1b88` activity stream does NOT help** (80 vs 82 at the same gap), so
   the hypothesis that it refreshes the clock is refuted. It is not the knob.
2. **The recipe above is wrong**: the code default is 4 ms
   (`REPLAY_CHUNK_GAP_MS = os.environ.get("AZOTH_CHUNK_GAP_MS", "4")`) while this
   runbook told operators to set 20. At 20 ms the replay is ~26 s — right on the
   client's ~27 s watchdog.
3. **32 heartbeats before the drain did not save A2.** A conflict-free post-replay
   stream is not enough to avoid the ~27 s kill on its own.

The trade is real and unresolved: a fast replay is warning-free but D logged a
`Cleanup()` ~3 min in; a slow one is calmer but risks the 27 s kill. **Do not treat
`AZOTH_CHUNK_GAP_MS=20` as the fixed answer** — measure the replay duration and the
warning count together (`python scripts/measure-run.py --label <name>`), because a
run's total warning count means nothing without knowing how long its replay took.

## Gate 8d — the server emits on its own tick (authoritative clock)

The fixes in 8c stopped the stall. This one removes the *coupling*: before it,
every periodic emitter was called from `on_app_data` (once per inbound
datagram), so the server's output rate was a function of the client's input
rate, and the replay pump only advanced while the client was talking.

Measured 2026-10-09, same run shape, before -> after:

| Metric | Coupled to inbound | Own tick |
| --- | --- | --- |
| `Pearson(inbound datagrams, outbound datagrams)` | **0.995** | **0.180** |
| Amplification (out/in) | 3.4:1 | **0.96:1** |
| Peak outbound/s | 286 | **99** |
| `v3-registered` per session | 8 | **1** |
| `OnLocalNetworkConnectionWarning` | 62 | **6** |

`PeerSession.tick()` runs from the UDP loop every `TICK_INTERVAL_S` (default
50 Hz, `AZOTH_TICK_HZ`), on a datagram *and* on an idle timeout — the socket
timeout IS the tick period, so the server keeps emitting when the client is
silent. Each emitter still gates itself on its own `_next_at`, so a faster tick
emits nothing extra. `on_app_data` is now the reactive path only (handshake
replies, ACKs, the V3 answer).

Two paths previously disagreed: the timeout path called 5 emitters and the
datagram path called 10, so `maybe_pump_replay` stopped entirely when the
client went quiet. There is now one list, in `tick()`, and
`TestAuthoritativeTick` fails if a periodic emitter is ever called from
`on_app_data` again.

## Gate 8c — the server must not stall its own UDP loop (found and fixed)

A possession run used to drop the transport ~35 s after spawn even with gates
6/7/8/8b set. The cause was **not** client-side. Two defects in the world
server's single-threaded UDP loop made it stop emitting entirely, and the
client drops the transport after 10 s of silence (that is the `ClientSDK:
Unexpected client disconnect! {"transportError":4}`):

1. **`log_event` reopened the log file per event.** Open + write + close on a
   file that reaches ~90 MB, once per event, inside the UDP loop. Under a
   client burst of 287 records in one second the server stopped logging for
   **27 s** (measured 2026-10-09, 16:57:55 -> 16:58:22). Fixed with a
   persistent append handle (`_log_write`).
2. **Every ACK was a separate datagram (1:1 with inbound).** Measured
   `Pearson(inbound, reply) = 0.995`; the server emitted up to 286 datagrams in
   one second for 185 inbound. The official capture is not 1:1 either (867 ch0
   in for ~3041 out). Fixed by coalescing ACKs by time (`ACK_COALESCE_S`,
   default 0.05 s); the CT_ACKS 0x40 form acks a *range*, so one datagram per
   window carries the same information.

Result of both fixes on a fresh run: `transportError` **0**, `disconnected
from REP` **0**, `Cleanup` **0**, and `InGame` held **10.1 minutes** (previous
best 0.6 min, and every earlier run died at ~35 s).

Related fixes on the same run:

- **Spurious V3 registrations.** The V3 trigger was `channel == 0 and size >
  64`, which also matched ordinary ch0 game messages. Of 17 ch0 records of
  size 256, only 2 parsed as V3 (one per connection) and 15 were game data —
  same size. The server answered all of them, so `v3-registered` fired 8 times
  while the client logged "received registration response from REP" only
  twice. Now a record must actually parse as V3
  (`parse_v3_request_or_lenient`). See the `v3_registration_payload()` fixture
  in `services/world/tests/test_rep.py` for the shape that parses.
- **Heartbeat retransmission.** The post-replay `0x15d` heartbeat carries a
  reliable wire flag (required: flags 0x20 made the client drop it silently)
  but the client never ACKs it, so every heartbeat was retried to the 6-try
  cap. Measured over 23 minutes: 1106 heartbeats produced 5437 resends, 46% of
  all outbound datagrams. `_send_datagram(track_reliable=False)` excludes
  self-superseding periodic records. Resends fell to 284.
- **Resend pump ran per inbound datagram.** Its per-call cap of 4 was really
  "4 x client traffic". Rate-limited by time instead
  (`RESEND_PUMP_MIN_INTERVAL_S`).

## Gate 8f — the activity clock must not wait for the replay (found 2026-10-10)

With gates 6/7/8/8b set the run still dropped the transport **26.8 s after the
spawn**:

```
00:29:47.751  GameConnectionWrapper: player spawn succeeds, in game
00:30:14.570  GameConnectionWrapper: disconnected from REP
00:30:14.570  ClientSDK: Unexpected client disconnect! {"transportError":4}
```

and the automatic retry never re-created the ClientContext, so every later
bundle was skipped (`clientContext == nullptr`) and the world stayed frozen on
the "Iniciando sesión…" popup.

The cause was in the world server, not the client. The two emitters that keep
the client's InGame activity clock alive — the `0x15d` heartbeat and the
`0x1096`/`0x1097` input response — both gated on `self.replay_queue` being
**empty**. The captured replay is 82 messages but **~1090 Carrier chunks**
(24 of the captured bodies are 46 KB), so at the recommended
`AZOTH_CHUNK_GAP_MS=20` it needs **~22 s** — inside the client's ~27 s
watchdog. The server log for that whole session contained **zero** `heartbeat`
and **zero** `input-response` events while the client's
`OnLocalNetworkConnectionWarning` climbed to 22.

**Fix:** those two emitters now gate on `_post_replay_started()` (the post-V3
greetings only) and run **concurrently** with the replay, which is what the
capture shows the real server doing — it pings while it streams. The state
stream deliberately keeps the drained-replay requirement, because it
re-applies the same captured bundles and double-applying state is not
idempotent client-side.

**Result of the re-run with the fix:** `transportError` **0**,
`disconnected from REP` **0**, `OnLocalNetworkConnectionWarning` **1**,
`clientContext == nullptr` **1**, session alive past **128 s**, and the world
renders with the player, the NPCs and the full HUD
(`research/sessions/2026-10-10/`).

If a run reaches the world and then dies at ~25-30 s, check this first:
`grep -c '"event": "heartbeat"' .azoth/logs/world.log` must be non-zero for the
session.

## Gate 8e — a 16-bit wire field must wrap (found 2026-10-10 on a long uptime)

The world server had been up for many hours and its log was filling with one
`tick-error` per second:

```
{"event": "tick-error", "error": "OverflowError: int too big to convert"}
```

7395 of them, starting at 22:10:23Z, with **no `CLOCK_SYNC` keepalive sent at
all** from that moment on (the last successful one logged seq 65533 at
22:10:22Z). The cause: `maybe_keepalive` passed the raw `next_out_seq` to
`clock_sync_datagram`, which called `seq.to_bytes(2, "big")`. That counter grows
without bound, so the moment it passed 65535 the call raised `OverflowError`,
the tick aborted, and every emitter ordered after the keepalive in `tick()` was
skipped for the rest of the process's life. The envelope sequence is a **u16 on
the wire**, so wrapping is the correct behaviour; `_send_datagram` already
masked its own copy, which is why the failure looked isolated to one emitter.

Fixed by routing every 16-bit wire field through a `_u16()` helper
(`seq`, `ack_first`, `ack_last`, `env_seq`) instead of calling `to_bytes`
directly, and by logging a **traceback** with a `tick-error` — 7395 identical
one-line errors named no function, so a dead keepalive was invisible in the log.

Lesson for any counter on the wire: mask at the point where the field is
written, not at the caller, and make a repeating tick error carry its
traceback.

## Gate 8b, measured 2026-10-09
**This lever alone was not enough** — it reduced the storm but the transport
still dropped at ~38 s, which is why gate 8c above exists. With gates 6/7/8 set
but the default 0.3 s resend interval, a run still died 38 s after `player spawn
succeeds`: the resend rate peaked at **223/s**, the first
`OnLocalNetworkConnectionWarning` landed in the same second, and the disconnect
followed 11 s later. Raising the interval to 1.0 s cut resends from **2293 to
1000** (an earlier reading of this run claimed 2292 -> 1; that count was wrong —
it summed a window from a different session, see the `.idx`-style lesson that the
world log accumulates runs). The lever (`rep.py` `RESEND_INTERVAL_S`, added
2026-10-07) is still worth keeping in the recommended block, but the resend storm
was a symptom of the stalled loop, not its cause.

Gate 6 is not a client patch: it is a **server replay setting**. The capture
redacted the author's own `PlayerComponentClientFacet` UUID to zeros while every
other player's facet UUID is in clear text, and the client's local-player gate
compares that UUID against the character UUID in its option store. With the
setting off, gates 1–5 can all pass and the screen stays black. See
`atlas/levers.md` (`AZOTH_REPLAY_LOCAL_PLAYER_UUID`).

The old Gate 7 model is superseded. On 2026-10-07, replaying `0x1096`/`0x1097`
correlated with fewer `State(InGame) is timeout` lines and fewer pixels in a
top-left band. The band did not measure the actual cable icon. Direct icon
measurement on 2026-10-10 found it red for 14 minutes while input responses and
REP traffic continued. A 2026-10-11 probe found `+0xAA0` stayed closed and the
`+0xAA8` input stamp stopped refreshing. The ALC producer/consumer remains the
connection blocker; do not call input-response a cable or connection fix. See
`atlas/levers.md` and the linked entries in `client-functions.json`.

## Gate 2 — the local CA (the silent one)

**Symptom.** `python az.py status` reports gateway, world, and caddy all
`running`; hosts are `in-sync`; DNS for a redirected host resolves to `127.0.0.1`
and `::1`. The client still hangs at the "press any button" title gate and the
gateway logs **zero** requests for the run.

**Cause.** Caddy terminates TLS for every redirected host with its *local*
issuing authority. Windows must trust the root Caddy is actually using. A fresh
`.azoth/caddy/data/` makes Caddy generate a **new** root with the same subject
(`CN=Caddy Local Authority - 2026 ECC Root`) but a different key, while the
machine's trust store still holds an older one. Same name, different
thumbprint — nothing reports an error.

Measured 2026-10-07:

| | SHA1 / thumbprint |
| --- | --- |
| Caddy on disk (`.azoth/caddy/data/caddy/pki/authorities/local/root.crt`) | `7FD5E96B26DF490396410A63F61E7C36607906AE` |
| Windows `Cert:\CurrentUser\Root` before the fix (stale) | `77231FD9DF0EAA20F64A12E0D85491DC98A15E45` |

Caddy's own log states the gap it could not close:
`pki.ca.local: failed to install root certificate ... failed to execute
keytool.exe: exit status 1`.

**Fix.** Import the current root and drop the stale one (no admin needed —
`CurrentUser\Root` is enough for the client):

```powershell
python scripts/trust-caddy-ca.py
```

**Verify before launching.** A Schannel client (what the game uses) must return
200 on a redirected host. `Invoke-WebRequest` uses the Windows store; the Git
Bash `curl` does **not** (it ships its own CA bundle), so a curl failure here is
not evidence.

```powershell
Invoke-WebRequest https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json -UseBasicParsing
```

**Do not** chase hosts, DNS, or "caddy is down" for this symptom. Hosts were
correct the whole time; the trust store was not.

## Gate 4 — REP (DTLS) trust: patch on disk, not with Frida

The client pins an embedded `CN=New World` certificate, so the REP handshake
against our world server fails with `tlsv1 alert unknown ca` until the verify
branch is forced. Two ways exist; **prefer the disk patch**:

| Method | Tool | When |
| --- | --- | --- |
| **Disk patch (preferred)** | `python scripts/patch-dtls-disk.py apply` / `restore` | Patches only the repo-local `private-client/runtime/Bin64/NewWorld.exe`. Deterministic, no injection, survives the whole run. Restore after every run. |
| Frida | `services/launcher/runtime-tools/frida-trust-patch.py` | Only if the disk patch is unavailable. Crashes the client when attached during startup mapping (see below). |

Measured: with the disk patch and **no Frida at all**, the client walked the
full REP path — `REP socket connection established` →
`received registration response from REP` → `WaitingForActorGameConnection` →
`spawn point found` → `WaitingForPlayerSpawn` → `LevelInfoChanged` →
`streamingGDEManager Initialize()` (`NewWorld_VitaeEterna`) →
`GDERenderManager Init()`.

## Frida vs raw memory writes

Two different jobs, two different tools. Do not use Frida for a fixed byte
patch.

| Job | Tool | Notes |
| --- | --- | --- |
| Fixed byte patch at a known VA | stdlib `ctypes`: `OpenProcess` + `ReadProcessMemory` + `VirtualProtectEx` + `WriteProcessMemory` | `services/launcher/runtime-tools/patch-*.py` and `scripts/patch-dtls-disk.py`. Deterministic, no agent, no crash surface. |
| Hook a function, read/write a runtime pointer, enumerate tables, call a target | Frida (`reverse/probes/client/frida-*.py`, `runtime-tools/frida-*.py`) | The only option for dynamic questions. |

**Frida crash signature (measured 2026-10-07).** Attaching the Frida
trust-patch while the client was still mapping produced an APPCRASH
`0xc0000005` in `ntdll.dll` (fault offset `0x165497`) ~6 s after process start,
before `Game.log` existed. The launcher then aborted with
`New World window not found`. The same run without Frida (disk patch only)
started normally. Treat "Frida during startup mapping" as unsafe and let the
client reach the menu first.

**Never** attach Frida, `ReadProcessMemory`, or a debugger to a process while
EAC is active or its state is uncertain. Confirm the exact target process first
(see `EAC.md` and `atlas/levers.md`).

## Patch timing — apply world-phase patches at character select

The `-Watch` patch set (spawn gate, predicate flag, watchdog, anticheat, spawn
ladder, EOS stub) exists for the **world** phase. Applying it during load is
what hangs the client.

Measured sequence of three runs on the same build:

| Run | Patches | Result |
| --- | --- | --- |
| 19:08 | none (no disk patch either) | reached `StartREPConnection`, failed with `transport_security_error` (Gate 4) |
| 19:41 | full set incl. Frida EOS stub, applied ~40 s after launch at the splash | **hung** in `WaitingForQueuedLogin`, process `Not Responding`, 191 threads in Wait |
| 19:58 / 20:06 | disk DTLS patch only, **no Frida** | reached the world: `Initialize()` → `Cleanup()`, `deferred actions` errors (Gate 5) |

**Rule:** launch clean, let the client reach character select, then apply the
world-phase patches, then click **Jugar**. For every patch that has a byte
equivalent, use the non-Frida script.

## Gate 5 — the black screen is the ClientContext predicate

The client reaches the world and renders black. `Game.log` shows the pair:

```
[ClientContext] Initialize()
[ClientContext] Cleanup()      <- same millisecond
```

then `NewWorld_VitaeEterna` loads with no live context and the log fills with
`Context: Exceeded max recursion for deferred actions`.

Root cause and the correcting patch are in
`services/launcher/runtime-tools/patch-predicate-flag.py` (it names the exact
VAs and the disassembly). `Initialize` self-cleans when its 7th argument is 0;
`LoadContextAndLevel` passes the virtual predicate's result, which is 0. The
patch forces the flag to 1 and NOPs the failure branch.

The `WaitingForPlayerSpawn is timeout` line that follows is the separate
per-state watchdog, patched by `patch-timeout-watchdog.py`. Both belong to the
world phase and belong at character select.

## Evidence paths — where files actually land

The launcher sets `$env:LOCALAPPDATA = private-client/profile/Local`, and
`Start-Process` does propagate an overridden environment. **The game ignores
it**: it resolves its profile through the Windows known-folder API
(`SHGetKnownFolderPath`), not the environment variable. Measured 2026-10-07:
with the launcher's override in place, `Game.log` and `savedata` were still
written under the real user profile.

| Artifact | Actual path |
| --- | --- |
| Client log | `%LOCALAPPDATA%\AGS\New World\Game.log` |
| Client savedata / options | `%APPDATA%\AGS\New World\savedata\` |
| Crash uploader log | `private-client/runtime/Bin64/logs/CrashUploader/` |
| Gateway traffic | `services/gateway/traffic.jsonl` |
| World REP traffic | `services/world/rep_traffic.jsonl` |
| Launcher output | `.azoth/logs/game-<stamp>.log` |
| Service logs | `.azoth/logs/{gateway,world,caddy}.log` |
| Windows crash reports | `%ProgramData%\Microsoft\Windows\WER\ReportArchive\AppCrash_NewWorld.exe_*` |

Two consequences worth remembering:

- Do not look for `Game.log` under `private-client/profile/`; it is not there.
  `private-client/` still holds the runtime tree, the executable copy, and
  `state/`.
- `traffic.jsonl` is the gateway's own log and may lag the Caddy access log
  during a burst. Caddy's access log (`.azoth/logs/caddy.log`, `logger ==
  "http.log.access"`) is the authoritative record of what the client actually
  requested, including hosts, URI, status, and remote port.
- `Game.log` is a SINGLE path per Windows user, so two concurrent private
  clients share it and each launch truncates it. That is a property of the
  binary, not of the launcher; see "Two clients at once" for the workaround and
  for the per-peer evidence in `.azoth/logs/world.log`.

## Gate 6 — local-player possession (server setting)

Measured 2026-10-07. The world server was started with
`replay_local_player_uuid = off`; the client reached `InGame`, `Initialize()`
ran without `Cleanup()`, `NewWorld_VitaeEterna` loaded, `GDERenderManager
Init()` ran — and the screen stayed black. Restarting the world server with
`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` on the same build rendered the world
**and possessed the player**: the town (Everfall/Brimstone Sands) drew with
NPCs, the third-person camera attached to the character, and the HUD, quest
tracker, minimap, and chat all appeared.

This is the documented possession lever (`atlas/levers.md`). It rewrites exactly
one redacted 16-byte span per large state bundle. Server log evidence:

```
{"event": "replay-local-player-uuid", "seq": 82, "selector": "character", "spans": 1, "spans_total": 161}
```

**The world server must be started with this setting for a usable private run.**
`python az.py world restart` inherits the environment of the shell that starts
it, so export it there (or use a wrapper); `python az.py dev` started earlier
will not pick it up.

## Historical Gate 7 — input-response traffic (not the ALC red cable)

This 2026-10-07 A/B is historical and its HUD conclusion was wrong. It replayed
the captured responses `0x1096`/`0x1097` to type `0x635` and reported fewer
timeout lines and fewer pixels in a top-left band. That band did not measure the
actual cable icon. The direct 2026-10-10 icon measurement found the cable still
red while input responses and REP traffic continued; on 2026-10-11, `+0xAA0`
stayed closed and `+0xAA8` stopped refreshing. The ALC producer/consumer remains
unknown.

| Session | `INPUT_RESPONSE` | warning callbacks | timeout lines | top-left band px (not the icon) |
| --- | --- | --- | --- | --- |
| 20:44 | off | 1 | 40+ | 86 |
| 21:21 | on | **0** | **0** | **0** |

These replies ride channel 0. They may affect a separate state-watchdog symptom,
but do not clear the measured ALC warning, establish user-visible connection
health, or move the player.

## Movement: the client streams input; the position reply has no valid client-side target

Measured on the same session, after `InGame`:

| Direction | Channel | Records |
| --- | --- | --- |
| client → server (`app-data`) | 1 | **3573** |
| server → client (`outbound-app-data`) | 1 | **0** |

The client streams channel-1 input continuously at ~20×/s and **that stream is now
identified**: wire `0x635` = index 1589 =
**`ActionListComponentServerFacet_ReceiveInputFromClient`**. Measured 2026-10-12 over a
whole session: **19676/19676** channel-1 records carry a valid `[crc32][len]` container,
all with target = the full 16-byte actor id `1a954abc4b3185bfbe37c3d8592618e0` and type
`0xC35`. Channel 0 carries the client's own ping (type 669, all-zero target) plus typed
requests, every one addressed to the same actor id. **StartMovementCommunicationMsg
(0x2D6) is absent from both channels.** So the input direction already works; what is
missing is an authoritative reply landing on a client object that implements
`IPositionReceiver`.

Method note (a trap): calling the server's `parse_datagram` on the logged `raw` fails with
`payload truncated: need 2048 bits, have 896`. The logged `raw_full` must go through
`parse_envelope` first, LZ4-decompressed when the envelope is `0x81`.

### Type names are recoverable from the binary

`private-client/runtime/typeindex.json` gives `typeIndex[wire index] = GUID`, and for each
GUID the client's `.rdata` holds it as a dashed lowercase string immediately preceded by a
NUL-terminated AZ RTTI name. This corrected two standing mislabels:

| wire | index | real name |
| --- | --- | --- |
| `0x635` | 1589 | `ActionListComponentServerFacet_ReceiveInputFromClient` |
| `0x1096` | 4246 | `TimeComponentClientFacet_SyncTimeChange` |
| `0x1097` | 4247 | `TimeComponentClientFacet_SyncDayPhase` |
| `0x2d6` | 726 | `StartMovementCommunicationMsg` |
| `0x1078` | 4216 | `ReceivePlayerPositionClientMsg` |

So `AZOTH_REPLAY_INPUT_RESPONSE` replays **time sync** messages, not input responses.

### The position reply's target is wrong, and the interface is not instantiated

The `RMIDispatch: The facet target ID couldn't be found` failure is real, and the previously
reported "fix" was a **false fix**: the blob that makes the dispatch succeed
(`93a3e477cb5fd51e`) is the client's `TimeComponentClientFacet` local id, so the position is
delivered to a time-sync facet. `FUN_143f97bf0` still returns 0 and nothing is applied.

The client **does** implement the interface: QueryInterface `FUN_143fadd00` (returns `this`
on a GUID match) at slot `+0x20` of vtable **`0x1482eb160`**, installed by the 6-byte
function at `0x143f983d0`; the interface is registered by name by `FUN_143f98300`; the RTTI
descriptor is `IPositionReceiver` at `0x1482ea920` with GUID
`{17C00FC6-074F-47EB-9640-9743D890ED6F}`. The blocker is that **no client-side RMI target
is an instance of it** (37063 targets, 225 distinct vtables, 0 positives). Probe:
`python az.py probe frida-position-target`.

`StartMovementCommunicationMsg` was re-run **reliably on channel 0** (the earlier attempt
was unreliable on channel 1, which the client never decodes — its body was already correct
at 20 bytes, verified against the client's own reader `FUN_146a55240`). Result: still no
receiver bound, and the actor-id reply still fails with **1581** facet errors. The client
never sends `0x2D6` either. Do not re-run it as a binding fix.

### Measuring the transform: use the client's own accessor

The client ships `nw_getPlayerPosition` ("print player position to the screen"). Its handler
`0x141015b30` calls **`FUN_140fddfa0(&holder)`** and prints
`*(float*)(holder+0x14c)`, `+0x15c`, `+0x16c` — the local player position in the client's own
format. `teleport` (handler `0x141020a40`) reaches `FUN_140fbf3b0`, so the client can also set
its own position. Use `python az.py probe frida-player-position`; validate with
`frida-position-validate`, which calls the client's own command handler and watches its printer
fire. Do NOT diff the `Transform` component's bytes: its head is a pointer/counter header, and
a 4 s W-hold changes nothing there — that measures the wrong bytes.

Measured 2026-10-12 (run `rcv2-073512`, in-world): **667/667 identical samples** at 0.2 s over
136 s, containing a 10 s W hold and a 4 s S control — position stayed
`(9343.6416, 2786.7327, 87.538)` — while the server logged 8184 app-data events carrying 7804
channel-1 records in the same window. Input leaves the client; the position does not change.

**The `ActorMover` family is NOT locomotion.** Its strings are server-side hub migration
(`Sending CommitMovement for actor`, `Destination hub timed out before receiving CommitMovement
or AbortMovement…`, `DelayMigrationsMsg`, `MoveActorToHubMsg`). The local-player plumbing is
`PlayerPositionTrackingComponent` (GUID `62620B33-6F37-418B-9C4F-62AD6058D54D`),
`PositionInTheWorldComponent`, `PositionalTicketingComponent`, `CameraPositionListener`.

**The `IPositionReceiver` is never created** (`installer 0x143f983d0` and `register 0x143f98300`
read 0 across a whole session), so no target id can apply a position.

### The live player entity's components (measured 2026-10-12)

`python az.py probe frida-player-components-full` dumps all 126 components and names them. The
entity carries `PlayerPositionTrackingComponent` (GUID `62620B33-6F37-418B-9C4F-62AD6058D54D`),
`CharacterComponent`, `Transform`, `TraversalComponent`, `CameraLockComponent`,
`PlayerInputFiltersComponent`, `MotionParameterSmoothingComponent`, `PlayerAOIComponent`,
`SpectatedPlayerComponent`, `SpectatorModeComponent`, `SkinnedMeshComponent`,
`FootstepComponent`, `PlayerSaveData` and more.

**Method trap that cost real time:** a component's VTABLE lives in `.rdata` (`r--`) while the
function pointer stored in it lives in `.text`. Checking `inCode(vtable)` therefore rejects
**every** component (126/126) as `badVtbl`. Check the resolved **function pointer** instead.

**Unresolved disagreement: RESOLVED 2026-10-12 — the physics components are ABSENT.** At three
instants of the same live entity (~4 s, +30 s, +120 s after spawn) `CharacterPhysicsComponent`
and `GameRigidBodyComponent` are neither in the 126-component list nor returned by the client's
own lookup `FUN_1413fb700` (both byte orders, controls positive), while the ADD hook `FUN_1413789c0`
was demonstrably live (24 adds, none on the player entity). The earlier claim came from
misreading a capture that says `physics_asked: {..."null"}` and lists both in `lost_named`. See
`physics_components_absent_RESOLVED_20261012`.

**The position path is replicated state, and its facets are missing.** On the live entity only
the bare `PlayerPositionTrackingComponent` is present; `PositionInTheWorldComponent{Client,Server}Facet`,
`PlayerPositionTrackingComponent{Client,Server}Facet`, `PositionalTicketingComponent{Client,Server}Facet`,
`CameraComponent` and `IPositionReceiver` are ALL absent. Static agrees that no RMI can be the
authoritative path: `PlayerPositionTrackingComponent` has only AI-debug messages,
`PositionInTheWorldComponent{Client,Server}Facet` have none, and
`PositionInTheWorldComponentServerFacet::InitializeReplicatedFields` exists, so the position
travels as replicated state (`MB::PositionInTheWorldReplicatedState`) on the AOI state-record
path — the same failure class as the unbound `GlobalStorageComponentClientFacet`. Do not write
another position RMI payload.

**Frida is a crash source on this build.** One crash's faulting module was
`frida-agent.dll_unloaded` at `0x9c7e0`. Attach as late as possible (at character select via
`private-run.py --no-play`), prefer hooks-only probes, and treat a session death as an invalid
attempt unless the faulting module is `NewWorld.exe`.

## The 20-minute return-to-menu path is ARMED BY THE REPLAY GAP (measured 2026-10-12)

`services/launcher/runtime-tools/patch-exit-to-menu.py` NOPs the correct call site:
`0x141004230` is one statement inside the teardown delegate `FUN_141004100`, and the
statement that leaves the world is the next virtual call, `0x14100425F`
(`call qword ptr [rax+0x1d8]` -> `FUN_141037b20`). One-variable A/B, no Frida in either run:

| run | `AZOTH_CHUNK_GAP_MS` | replay | 20-minute exit |
| --- | --- | --- | --- |
| `exitA-gap20-012032` | 20 | 29 s | **fired at 20:00.398** |
| `exitval2-202053` | 4 (default) | 10 s | did not arm (session ended 26:33 by a REP disconnect) |

With the patch applied the delegate ran and the patched call was skipped:
`exiting to main menu` 0 and `Cleanup()` 0, where the pre-patch runs logged both.
**It is still not a session fix.** The same delegate tears the connection down at
`0x141004230` *before* the patched call, so the client stopped sending traffic at
20:00.398 — zero server-side events after that — and a screenshot taken 5 minutes later
still showed the world, i.e. a frozen last frame. To keep a session past 20 minutes the
**arm** must be prevented. `FUN_146420610` (`CGame::ActorContainerDisconnect`) has **11
callers**, so its log line marks *some* caller, not the delegate; only its absence is
decisive about the delegate. Atlas: `exitA_gap20_run_outcome_20261011`,
`chunk_gap_decides_the_20minute_arm_20261011`, `exit_delegate_call_site_verified_20261011`.

The HUD red cable was RED at every 20 s sample of every recent run, including past the
20-minute mark. No run has yet reached the 30-minute acceptance.

**Launch trap re-confirmed 2026-10-12:** starting the client while Caddy is still binding
makes the CMS manifest return 502, and the client then stalls on the Aeternum splash with
`Channel Service data provider: Unexpected response code: 502 ... All attempts (5)
exhausted` followed by `Auth manager does not exist`. Wait until the manifest answers 200
(check with PowerShell `Invoke-WebRequest`, Schannel like the game) before launching.

## Historical Gate 8 — the transport burst (intermittent ~16 s post-spawn disconnect)

Measured 2026-10-07. Some sessions die with `Unexpected client disconnect!
{"transportError":4}` a very consistent **15–17 seconds after spawn**. The
client then retries automatically, but the retry gets
`HandleUnexpectedMessage skipping ReceiveStateBundle ... clientContext ==
nullptr` on every bundle (the documented "only the first world attempt is
valid" behaviour), so the session is effectively lost.

Observed mechanism (server `rep_traffic.jsonl` + client `Game.log`):

1. The replay delivers the captured state as ~1100-byte chunks plus resends.
2. The client stops sending anything.
3. **~10 s later** it declares `transportError 4`.
4. The server logs a matching silence window (26 s in one measured run).

The rate is what differs between a session that survives and one that does not:

| Session | replay-chunks | resends | outbound/s | replay completed | result |
| --- | --- | --- | --- | --- | --- |
| 22:33 (clean) | 1278 / 60 s = **21/s** | 1034 / 60 s | ~63/s | yes | 25 min clean |
| 23:03 (failed) | 1093 / 12 s = **91/s** | 508 / 12 s | ~200/s | **no** | `transportError 4` at 15.6 s |

The failing run pushed roughly 3× the outbound rate and had not finished the
replay when the client gave up. This was a useful correlation from two runs, not
a general pacing rule; later A/Bs and the compressed-envelope server bug changed
the diagnosis. REP transport can survive, while the ALC warning and 20-minute
menu exit remain separate open issues.

Mitigation levers:

| Lever | Default | Effect measured 2026-10-07 |
| --- | --- | --- |
| `AZOTH_CHUNK_GAP_MS` | 4 | 20 ms passed one old run but was slow and risky in later A/Bs. Recorded 4/8 ms runs had no transport error; a 4 ms run also had a later `Cleanup()`. No value is a universal fix. |
| `AZOTH_RESEND_INTERVAL_S` | 0.3 | Minimum seconds before the same reliable datagram is retransmitted. 1.0 lowered the resend peak from 650/s to 478/s and the transient cable burst from 4 warnings to 3. Modest; keep 0.3 unless tuning. |

Note the replay takes longer to drain with a larger gap, so increase any wait
before interpreting a run.

**Single historical pass, 2026-10-07**: `AZOTH_CHUNK_GAP_MS=20` gave one run
with `transportError 4` **0** and a completed replay. Do not use that result to
recommend 20 ms: later paired runs found it slower and closer to the watchdog.
Use the current default for a baseline and change pacing only when a fresh A/B
isolates that variable.

**Historical 2026-10-08 run**: a run with the then-recommended config
(`LOCAL_PLAYER_UUID=character`, `INPUT_RESPONSE=1`, `CHUNK_GAP_MS=20`) stayed
**InGame for 20 minutes** (02:51:31 -> 03:11:32), server steady at 21 app-data/s
+ 25 outbound/s with **0 resends**, then the client disconnected **cleanly**
(`ActorContainerDisconnect`, no `transportError`, no `OnConnectionFail`). This
is an observed 20-minute boundary, not proof that the session remains in-world
past the separate return-to-menu threshold.

**Tradeoff (measured).** Pacing lengthens the replay drain, and the resend storm
builds up while it drains. In the verified run the server sent **650 resends in
one second** at the storm peak (23:12:22), and the client logged **4**
`OnLocalNetworkConnectionWarning` in a 0.3 s burst at 23:12:24 — the same second
the replay completed. Immediately after, the server settled to 25 outbound/s and
**0 resends**. That callback burst is distinct from the actual ALC/HUD icon,
which later measurements found remained red. Do not infer icon health from the
callback count or the server's resend rate.

This is separate from world entry and the ALC/HUD gate. Record transport errors,
replay pacing, actual icon color, and session duration as separate results.

## The working sequence (cold setup → world attempt)

Manual sequence:

```text
1. python az.py mode status                 # expect: in-sync
2. python scripts/trust-caddy-ca.py         # Gate 2; verify with Invoke-WebRequest
3. export AZOTH_REPLAY_LOCAL_PLAYER_UUID=character   # Gate 6 (world env)
   export AZOTH_REPLAY_INPUT_RESPONSE=1              # Gate 7 (world env)
4. python az.py dev                         # gateway + world + caddy
5. python az.py status                      # exactly one of each
6. python scripts/patch-dtls-disk.py apply  # Gate 4; no Frida
7. python az.py game                        # launcher, no -Watch
8. drive splash -> character select         # scan-code SendInput, Space = 0x39
9. apply world-phase patches at char select # predicate flag, watchdog, ...
10. click Jugar
11. read Game.log for the first missing boundary
12. python scripts/patch-dtls-disk.py restore   # leave the copy pristine
```

**Automated sequence** (steps 7-11 in one command, for overnight work):

```text
python scripts/private-run.py
```

It launches the client, passes the splash gate with a scan-code Space, settles
for the frontend, applies the world-phase patches, retries the Play click until
the login queues, and prints a verdict (`InGame reached, player possessed` /
the failure boundary). Options: `--no-launch`, `--no-play`, `--skip-splash`,
`--settle <s>`, `--play-attempts <n>`. Verified 2026-10-07: verdict `InGame
reached, player possessed`, 0 warnings.

Note: `OnCampfireLoginComplete` fires during the **initial** load, before the
splash gate, so it is not a character-select marker. The script waits a fixed
settle window instead and retries the click.

Historical 2026-10-07 result: with steps 1-10 the world rendered and the player
was possessed (`Initialize()` without `Cleanup()`, `player spawn succeeds, in
game`, `InGame`). The old phrase "physics active" was not backed by a transform or
controller measurement. A recorded 25-minute run with zero Game.log warnings is
not proof that the real HUD cable cleared or that the separate session-lifetime
gate passes; later runs measured a red ALC/HUD cable and an approximately
20-minute return-to-menu path. Treat this as the entry/possession baseline only.

Use `scripts/shot.py` for the window screenshot: the client can open on a
secondary monitor, and a full-screen capture then comes back black.

## Input reaches the client only as real SendInput with a scan code

The engine reads Raw Input. `scripts/send-input.py` with a virtual key
(`key 0x20`) did **not** advance the title gate; `scripts/hold-key.py` with a
real scan code (`0x39` for Space) did. Mouse clicks need
`scripts/click-window.py` and a DPI-aware process. `focus-window.py --check`
proves the target window is actually foreground before a key is sent.

## Two clients at once (second client, same world server)

Prepared 2026-10-19. Two private clients can run at the same time against one
local stack, each with its own window, and the server gives each one its own REP
session. What it does **not** give you yet is presence: both clients are the same
character and there is no peer-to-peer replication, so "each can see the other"
is not implemented (see "Identity" below). Treat "two clients connect" and
"each client sees the other" as separate results, like every other gate here.

### Start them

```powershell
# 1. the stack and the FIRST client, exactly as before
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'
python az.py dev
python scripts/patch-dtls-disk.py apply
python scripts/private-run.py                       # client 1 (unchanged path)

# 2. the SECOND client: own launcher state, same executable, same server
python scripts/run-second-client.py                 # = private-run.py --instance 2
```

The mechanism is one launcher flag: `Start-NwPrivate.ps1 -Instance N` (or
`AZOTH_CLIENT_INSTANCE=N`). Instance 1 keeps every historical path, so a
single-client run is unchanged. To start the second client by hand:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File services/launcher/src/Start-NwPrivate.ps1 -Instance 2
```

`scripts/run-second-client.py` adds only the preflight that the second launch
cannot break the first one (DTLS patch present, shared log snapshotted) and then
runs `scripts/private-run.py --instance 2`.

### What collides, and what was done about it

| Thing | Collides? | Handling |
| --- | --- | --- |
| Window title | **yes** — both windows are `New World` | the runner resolves the launcher's pid (`private-client/state[/instance-N]/game.pid`) and targets that HWND for the Space key and the Play click. The world-phase patch scripts still select `send-input.find_windows("New World")[0]`, so the runner refuses to patch unless that topmost window is the client it drives. |
| Launcher state (`game.pid`, `eos.pid`, `client-source.json`, TEMP) | **yes** | per-instance dirs: `private-client/state` for instance 1, `private-client/state/instance-N` for N>1; TEMP goes to `.azoth/tmp/instance-N`. The launcher also only refuses a second copy of the *same* instance. |
| `Game.log`, `savedata` | **yes, unavoidable** | the client resolves both through the Windows known-folder API and ignores the launcher's `LOCALAPPDATA`/`APPDATA` override (measured 2026-10-07). Every launch **truncates** `Game.log`, so the second launch erases the first client's log. `run-second-client.py` snapshots it to `.azoth/logs/game-before-instance2-<stamp>.log` before launching, and a two-client run is verified in `.azoth/logs/world.log`, where every REP event carries its `peer`. |
| Private executable | shared **on purpose** | one 179 MB copy (`private-client/runtime/Bin64/NewWorld.exe`), one DTLS disk patch, both clients. A separate `-RuntimeRoot` would need its own DTLS patch and `scripts/patch-dtls-disk.py` only patches the default path. |
| REP source port | no, **inferred** | the client starts at 27000 for every process and the seen sequence skips values (`rep_traffic.jsonl`: `27001 -> 27003`), so a port it cannot take does not pin it to 27000 and the second client should take the next free one. Not yet observed with two live clients — it is the first thing to check in a two-client run. |
| Gateway identity | **yes** | see "Identity" below — the gateway serves one fixed character and persona, so both clients are the same character. |
| `-Watch` (Frida set) | **yes** | refused for `-Instance > 1`: those scripts select the first `NewWorld.exe` window and would patch the other client. Use the fixed-byte patches. |

### The server already supports two concurrent peers

Read from the code and asserted by a test (no live run needed):

| Fact | Evidence |
| --- | --- |
| Sessions are keyed by `(ip, port)`, not by IP or character | `services/world/src/azoth_world/rep.py:5143` (`self.peers: dict[tuple[str, int], PeerSession]`), `:5228` (a new `PeerSession` per unseen peer) |
| Every session is ticked every loop iteration | `rep.py:5161` |
| Replay, state stream, reliable-resend table, learned actor id and V3 identity are **per session** | `rep.py:2407` (`class PeerSession`), `:2443`, `:2565`, `:2668` |
| Captured replay bodies are shared but immutable (`bytes`), the queues are not | `replay_store.py` returns new bodies; `_arm_replay` builds a fresh `replay_queue` per session |
| `dtls-established` now logs the live session count | `rep.py:2586` (`"peers": len(server.peers)`) |
| Test | `services/world/tests/test_rep.py::TestTwoClientsShareOneWorldServer` — two real DTLS clients through the live loop, asserting two sessions and the logged count |

### Identity: both clients are the SAME character

Measured/read 2026-10-19. Two facts make the two clients identical on the wire:

1. The gateway serves one fixed identity — `AZOTH_CHARACTER_ID` and
   `AZOTH_PERSONA` in `services/gateway/src/azoth_gateway/routes/identity.py:11`.
   Both logins get the same character, so both V3 registrations carry the same
   `character_id` (the server keeps it per session, `rep.py:2435`, but the value
   is equal).
2. The replay is one capture. `replay_local_player_uuid=character` rewrites the
   same redacted span in each session's own copy of the same bundles, and the
   actor id `1a954abc4b3185bfbe37c3d8592618e0` (`rep.py:4465`, the position-reply
   fallback) is the capture's actor, not a per-client one. `client_actor_id`
   (`rep.py:2668`) *is* per session and is learned from that client's own
   channel-1 record — but both clients stream about the same actor.

So each client possesses its own copy of the captured player. Neither renders
the other as a distinct actor, and no code iterates `self.peers` to broadcast one
client's state to another (grep `for peer`/`broadcast` in `rep.py`: none). Making
them see each other needs (a) a distinct character per login in the gateway and
(b) peer-to-peer presence (actor registration plus state records for the other
peer), which does not exist yet. `AZOTH_NPC_DUPLICATE_SLOT` / `AZOTH_SERVER_ENTITY`
create a *second* actor from the capture, which is the closest existing
mechanism and is not per-peer.

### Verify a two-client run

```powershell
# two sessions, and the count each one reported on establishing
grep '"dtls-established"' .azoth/logs/world.log | tail -4
# expect: peer 127.0.0.1:27000 peers 1  and  peer 127.0.0.1:2700N peers 2
```

A second client whose REP never appears here is a Gate 4 or port problem, not a
window problem: check `transport_security_error` in its `Game.log` first.

Known unverified assumption: the two clients must end up with different REP
source ports. The port sequence is per process starting at 27000 and it skips
ports it cannot take (see the collision table), but no run has yet had two live
clients at once, so if the second client stalls in `WaitingForREPConnection`
with no `dtls-established` line, suspect the port before the transport.

## Quick triage table

| Observation | First thing to check |
| --- | --- |
| Stuck at title gate, 0 gateway rows | Gate 2 — Caddy CA trust |
| `tlsv1 alert unknown ca` in world.log | Gate 4 — disk DTLS patch missing/not applied |
| `transport_security_error (2)` | Gate 4 |
| Process `Not Responding` after load | patches applied too early; relaunch and patch at char select |
| `Initialize()` then `Cleanup()` | Gate 5 — predicate flag patch |
| `Initialize()` alone, world loads, still black, no player | Gate 6 — world server `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` |
| `Exceeded max recursion for deferred actions` | Gate 5 symptom, not a separate bug |
| `WaitingForPlayerSpawn is timeout` | watchdog patch, at char select |
| Red cable in the HUD | ALC input stamp/door: inspect `+0xAA8`/`+0xAA0`; input-response replay is not a fix |
| Two gateway/world processes by command line | process hygiene — kill duplicates |
| APPCRASH `c0000005` in `ntdll` at startup | Frida attached during mapping — use the disk patch |
| `transportError 4` or REP disconnect | Check the current server error and decompression/loop path in `STATUS.md`; do not increase replay gap without a fresh A/B that isolates it |
| Second client's window appeared but its `Game.log` is gone/mixed | both clients share `%LOCALAPPDATA%\AGS\New World\Game.log` and each launch truncates it — verify that client in `.azoth/logs/world.log` (`peer`, `peers`) instead |
| Only one `dtls-established` in `world.log` with two clients running | the second client never reached REP: Gate 4 (`transport_security_error`) or its source port is taken — check its own log lines and the `peer` ports |
| `FAIL: the patch scripts would target hwnd=…` | with two clients the patch scripts pick the topmost `New World` window; bring the target client's window to the front and re-run (they write process memory, so the runner refuses) |
