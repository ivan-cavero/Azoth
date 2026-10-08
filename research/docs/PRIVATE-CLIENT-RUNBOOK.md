# Private client runbook — cold setup, patch policy, and evidence paths

Operational reference for running the private (no Steam, no EAC) client and
for choosing how to observe or patch it. It records what actually works, what
silently fails, and where each artifact lands. Method rules stay in
[LESSONS.md](LESSONS.md); the wire contract stays in
[REP-PROTOCOL.md](REP-PROTOCOL.md) and [JAVELIN-PROTOCOL.md](JAVELIN-PROTOCOL.md);
the phase-by-phase server obligations are in
[SERVER-CONTRACT.md](SERVER-CONTRACT.md).
Build analyzed: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`.

This file answers one question: **"I asked for a private run and it did not
behave; which layer is lying?"** Read it before touching hosts, certs, patches,
or Frida.

## The recommended configuration (one block)

```powershell
# world-server environment (gates 6, 7, 8) — export BEFORE starting the stack
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'   # the world renders + player possessed
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'           # no red cable, no InGame timeout
$env:AZOTH_CHUNK_GAP_MS             = '20'          # no post-spawn transport drop
python az.py dev

# once: trust Caddy's CA (gate 2)
python scripts/trust-caddy-ca.py

# per run: DTLS disk patch (gate 4), then drive the whole run (gates 5-8)
python scripts/patch-dtls-disk.py apply
python scripts/private-run.py

# after the run
python scripts/patch-dtls-disk.py restore
```

With that block a run reaches `player spawn succeeds`, the world renders with a
possessed player, and the session stays up with **0**
`OnLocalNetworkConnectionWarning`, **0** `State(InGame) is timeout`, and **0**
`transportError`. Everything below explains why each line is needed and what
breaks without it.

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
| 7 | Post-replay server traffic | `replay_input_response=1` on the world server | player and world render, but the red cable appears and `State(InGame) is timeout` repeats |
| 8 | Transport burst | pace the replay (`AZOTH_CHUNK_GAP_MS`) | `transportError 4` ~16 s after spawn, then the retry cannot recreate the context |

Gate 6 is not a client patch: it is a **server replay setting**. The capture
redacted the author's own `PlayerComponentClientFacet` UUID to zeros while every
other player's facet UUID is in clear text, and the client's local-player gate
compares that UUID against the character UUID in its option store. With the
setting off, gates 1–5 can all pass and the screen stays black. See
`atlas/levers.md` (`AZOTH_REPLAY_LOCAL_PLAYER_UUID`).

Gate 7 is also a server setting. The replay answers the client's player-state
stream once and then goes quiet; the client's HUD cable and its per-state
watchdog react to that silence. `AZOTH_REPLAY_INPUT_RESPONSE=1` re-sends the two
captured reply bodies (`0x1096`/`0x1097`) on a 1 s period. Measured A/B: cable
warnings 1 → 0, `State(InGame) is timeout` lines → 0, red HUD pixels 86 → 0, and
a 13+ minute session stayed `InGame` with no `OnConnectionFail`. See
`atlas/levers.md` (`AZOTH_REPLAY_INPUT_RESPONSE`).

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

## Gate 7 — keep talking after the replay drains (the red cable)

Measured 2026-10-07. The replay delivers the captured world state once and then
the server only pings `0x15d`. The client's HUD then shows the red cable
(`OnLocalNetworkConnectionWarning`) and the per-state watchdog logs
`State(InGame) is timeout` every 30 s. The capture's server did not go quiet: it
answered the client's local-player state stream (type `0x635`, channel 1) with
`0x1096` (80 B) and `0x1097` (24 B). Re-sending those two captured bodies on a
1 s period (`AZOTH_REPLAY_INPUT_RESPONSE=1`) removed the cable and the timeout
entirely.

| Session | `INPUT_RESPONSE` | cable warnings | timeout lines | red HUD px |
| --- | --- | --- | --- | --- |
| 20:44 | off | 1 | 40+ | 86 |
| 21:21 | on | **0** | **0** | **0** |

This rides channel 0 (the typed stream). It fixes stability, **not movement**.

## The movement frontier is a missing server reply, not a client bug

Measured on the same session, after `InGame`:

| Direction | Channel | Records |
| --- | --- | --- |
| client → server (`app-data`) | 1 | **3573** |
| server → client (`outbound-app-data`) | 1 | **0** |

The client broadcasts its local-player state on channel 1 (type `0x635`); our
replay server never answers on channel 1/2. The capture does not contain that
reply stream, so it has to be constructed server-side. This is the same finding
recorded as the movement blocker in `STATUS.md`; it is repeated here only to
mark where the private-run gates end and the protocol work begins.

## Gate 8 — the transport burst (intermittent ~16 s post-spawn disconnect)

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
replay when the client gave up. Working conclusion: **the replay burst starves
the client's network thread**, and the client's own transport watchdog then
fires.

Mitigation levers:

| Lever | Default | Effect measured 2026-10-07 |
| --- | --- | --- |
| `AZOTH_CHUNK_GAP_MS` | 4 | **The decisive one.** 20 fixed the drop: `transportError 4` 0, `is timeout` 0, replay completed, world rendered. |
| `AZOTH_RESEND_INTERVAL_S` | 0.3 | Minimum seconds before the same reliable datagram is retransmitted. 1.0 lowered the resend peak from 650/s to 478/s and the transient cable burst from 4 warnings to 3. Modest; keep 0.3 unless tuning. |

Note the replay takes longer to drain with a larger gap, so increase any wait
before interpreting a run.

**Verified 2026-10-07**: `AZOTH_CHUNK_GAP_MS=20` gave a run with `player spawn
succeeds`, `transportError 4` **0**, `State(InGame) is timeout` **0**, and a
completed replay — the world rendered with the player possessed. Use 20 (not 4)
for a session that has to survive.

**Long-run validation 2026-10-08**: a run with the full recommended config
(`LOCAL_PLAYER_UUID=character`, `INPUT_RESPONSE=1`, `CHUNK_GAP_MS=20`) stayed
**InGame for 20 minutes** (02:51:31 -> 03:11:32), server steady at 21 app-data/s
+ 25 outbound/s with **0 resends**, then the client disconnected **cleanly**
(`ActorContainerDisconnect`, no `transportError`, no `OnConnectionFail`). That is
the target steady state for any A/B baseline.

**Tradeoff (measured).** Pacing lengthens the replay drain, and the resend storm
builds up while it drains. In the verified run the server sent **650 resends in
one second** at the storm peak (23:12:22), and the client logged **4**
`OnLocalNetworkConnectionWarning` in a 0.3 s burst at 23:12:24 — the same second
the replay completed. Immediately after, the server settled to 25 outbound/s and
**0 resends**, and the session then ran clean. So the cable shows briefly during
the drain and clears; it is not the escalating counter of gate 7. A run is
healthy if the warnings stop once `replay-complete-quiet` appears.

This is separate from gates 6 and 7: those decide whether the world renders and
whether the HUD cable appears; this one decides whether the session survives at
all.

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

Confirmed end to end on 2026-10-07: with steps 1–10 the world rendered and the
player was possessed (`Initialize()` without `Cleanup()`, `player spawn
succeeds, in game`, `InGame`, physics active), and with step 3's second variable
the session ran 25 minutes with **0 warnings and 0 timeouts**.

Use `scripts/shot.py` for the window screenshot: the client can open on a
secondary monitor, and a full-screen capture then comes back black.

## Input reaches the client only as real SendInput with a scan code

The engine reads Raw Input. `scripts/send-input.py` with a virtual key
(`key 0x20`) did **not** advance the title gate; `scripts/hold-key.py` with a
real scan code (`0x39` for Space) did. Mouse clicks need
`scripts/click-window.py` and a DPI-aware process. `focus-window.py --check`
proves the target window is actually foreground before a key is sent.

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
| Red cable in the HUD, `State(InGame) is timeout` repeating | Gate 7 — world server `AZOTH_REPLAY_INPUT_RESPONSE=1` |
| Two gateway/world processes by command line | process hygiene — kill duplicates |
| APPCRASH `c0000005` in `ntdll` at startup | Frida attached during mapping — use the disk patch |
| `transportError 4` ~15–17 s after spawn, then `clientContext == nullptr` | Gate 8 — replay burst too fast; raise `AZOTH_CHUNK_GAP_MS` |
