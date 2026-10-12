# Overnight report — 2026-10-11 (06:00 → 08:40 UTC)

> **Historical snapshot, superseded later on 2026-10-11.** The run measurements below are retained as evidence from 06:00-08:40 UTC, but several conclusions were hypotheses and are no longer current. Use [`STATUS.md`](../../STATUS.md), [`docs/ROADMAP.md`](../../docs/ROADMAP.md), and the cited atlas records for the active diagnosis. REP uptime is separate from the red ALC/HUD icon; decoding wire 4216 is separate from successful facet dispatch; screenshots of possession do not prove physics or movement.

Session goal (user): a **stable world with no connection error**, **physics**, **NPCs**,
and the ability to **move**, without stopping. This file is the deliverable report.
Detailed evidence lives in the atlas entries it cites; raw captures stay ignored.

Build in scope: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`
(`[RETAIL].Javelin.1.400.6031.6004151`). Private client only; Steam untouched; EAC absent.

---

## 1. Headline results

| # | Result | Status |
| --- | --- | --- |
| 1 | **REP transport remained alive; the client-visible ALC warning stayed red** | measured: 1 h 30 min in world, `transportError` 0, `disconnected from REP` 0; this does not pass the HUD/ALC gate |
| 2 | **The HUD tracks stale ALC response age** | amber threshold 2 s; red threshold 15 s; `+0xAA8` stops advancing while REP can remain alive |
| 3 | **The client's record container is now decoded**: `[crc32 BE][len BE][16-byte target][00 01][type][body]` | verified on 40 279/40 279 channel-1 and 285/294 channel-0 records |
| 4 | **The client emits exactly ONE type on its streaming channel** (ch1, type `0x635`) | 17 912 records in one session; the server answers on channel 0 |
| 5 | **The InGame watchdog is NOT the 20-minute exit** | refuted by measurement, not by argument |
| 5b | **The 20-minute deadline is exact and reproducible** | six runs: 20:00, 20:01, 20:01, 20:02, 20:00, **20:00.404** |
| 6 | **A queued-delegate path and teardown candidate were observed** | later callsite patch was refuted: the client still returned to menu at 20:00.4 |
| 7 | **Reliable 4216 reaches the message reader** | 212 reader calls measured; later RMI dispatch fails 103 times for a missing facet target |

The table separates direct measurements from the interpretations made at that time. Several interpretations were later corrected; read the supersession note and current status before choosing an experiment.

---

## 2. The connection error the user sees (cable icon with red X)

**The HUD displays ALC last-response age: amber after 2 s, red after 15 s.**

* The HUD icon is a pure function of one number: `now - *(conn+0xAA8)`, compared
  against two thresholds (`FUN_14486c740`, per frame). The thresholds are zero in
  the file, so they come from cvars.
* The cvars are registered by the client's own registrar `FUN_1410825e0`
  (`client_javelin_cvar_registrar` in the atlas):
  * `javelin.alc-server-timeout-for-input` = **2000** ms
  * `javelin.alc-server-timeout-for-ui` = 2000 ms
  * `javelin.alc-server-timeout-for-ui-high` = 15000 ms
* **Both thresholds were then read out of the live process** (probe
  `frida-hud-thresholds`): red = **15000** ms, amber = **2000** ms. So the state machine
  is `age <= 2 s` blue, `2 s < age <= 15 s` amber, `age > 15 s` red — exactly the
  blue → amber → red sequence described, and it becomes permanent ~15 s after connecting
  once the HUD stamp stops advancing after its observed initialization/replay update, the age passes the live red threshold. Atlas: `hud_connection_thresholds_measured` and `alc_pointer_never_opens_live_20261011`.
* Live probes found two object classes with `+0xAA8`. The HUD class stamp moved once at replay completion and then stopped; the later ALC-door probe found `+0xAA0` closed on both classes. A hardware watchpoint caught no recurring stamp writes during its window, and static analysis found no recurring writer in this build. Do not conflate the two objects or infer that the ALC conversation opened.
* In the measured steady state, once the HUD stamp stops advancing, its age passes the live 15 s red threshold. The capture shows a stale ALC response indicator; it does not establish that the ALC pointer opened.

**What this proves:** the red HUD cable tracks a stale ALC response stamp, and it can remain red while REP transport is healthy. It does not establish that ALC and movement share the same root cause. The server has sent input-response messages and `StartMovementCommunicationMsg` without opening `+0xAA0`; the missing ALC handshake producer is still unknown.

**The multi-object timestamp poke is not a server fix.** An earlier one-object poke did not clear the icon because several objects carry `+0xAA8`. Do not claim the real connection is fixed by changing HUD memory; the live protocol gate remains the closed ALC door and the actual icon must clear through the supported conversation.

---

## 3. The protocol: what was decoded tonight

### 3.1 The client's record container (new, and a strong suspect)

Every non-chunked client→server Carrier DATA record on channels 0 and 1 is:

```
[u32 BE  crc32(payload)] [u32 BE  len(payload)] [payload]
payload = [16-byte target id][00 01][prefix-varint wire type][body]
```

Verified over one live session (`client_record_crc32_container`):

| channel | records checked | CRC + length both correct |
| --- | --- | --- |
| 0 | 294 | 285 (the 9 misses are the 1115 B / 239 B MF_CHUNKS transfers) |
| 1 | 40 279 | **40 279 / 40 279** |

**Historical framing hypothesis, superseded:** the server originally used the captured `[vlq32 len]` form. That alone did not prove the channel-1 reply was discarded. A later reliable channel-0 run reached the 4216 reader 212 times; `flags 0x21` was the measured decoder gate. It then failed RMI dispatch because the target facet was absent. Do not spend another run on container layout without evidence that the current record fails earlier.

### 3.2 What the client actually sends (new)

Per-record decode of a full session, by channel and wire type:

* **channel 1: only type `0x635`** (GUID `01346CCD-785E-448D-A429-4B281972B1D7`),
  17 912 records, sizes 92/93/108/117/119/123/138/152/153 B, 17 698 of them 119 B.
  This type is not in the Javelin registry and is the local-player state stream.
* **channel 0**: `0x15d` (the client's own ping, target id zero) plus typed requests.

So the client's streaming traffic is one unnamed type on channel 1, and the server
answers it on channel 0 with `0x1096`/`0x1097`. Nothing in the client's own traffic
carries a position.

### 3.3 Position messages (the movement family)

Later measured result: reliable wire 4216 reaches the client resolver and reader 212 times; `Game.log` then reports 103 RMI target-not-found failures for `targetLocalId`, and the static lookup finds no bound `IPositionReceiver`. The message is decoded, but its position is not applied. Unreliable flags `0x20` do not reach the reader; reliable `0x21` opens decoding only. The earlier claim that the player walked from screenshot differences was retracted.

W also produced no movement-family message in the sampled run, and channel-1 `0x635` did not provide a measured transform change. Read the live player transform and trace the input consumer before deciding whether a server reply, ALC handshake, or facet binding is the next fix.

---

## 4. Stability: the 20-minute self-exit

Measured five times: the client leaves the world **exactly 20:00 after
`player spawn succeeds`** (20:00, 20:01, 20:01, 20:02, 20:00), cleanly —
`CGame::ActorContainerDisconnect` → `CGame exiting to main menu` → `Cleanup()`,
`transportError` 0, `OnLocalNetworkConnectionWarning` 0. Not a network failure.

**Tonight the caller was caught live** (probe `frida-20min-exit`, 06:59:50.412Z,
20:00.334 after the spawn):

```
CGame::ActorContainerDisconnect   FUN_146420610
  <- FUN_141004100   queued AZStd::delegate (action 1/2 = teardown)
  <- FUN_14107fb40   deferred-action queue drain
  <- FUN_14147e7c0   per-frame scheduler (QueryPerformanceCounter)
  <- FUN_1471586e0 <- FUN_146dbd0df <- FUN_14646c720 <- FUN_14646d3ac <- FUN_1410443a0
```

The delegate's whole disconnect body is **one 5-byte call at `0x141004230`**
(`e8 db c3 41 05`). Atlas: `exit_to_main_menu_delegate_chain`.

**Refuted in the same session:** the InGame watchdog `FUN_146445e10` is *not* this
timer. With its return patched to 0 (the launcher's own patch) the log line still
prints every 30 s — the log call precedes the return — but no disconnect notice is
sent, and the session still left at exactly 20:00. Atlas: `ingame_activity_watchdog`.

**Sixth measurement, and it rules the position reply out as a cure.** The final run of
the night: `player spawn succeeds` 08:21:06.197Z → `ActorContainerDisconnect`
08:41:06.601Z = **20:00.404**, with `ReceivePlayerPositionClientMsg` streaming on
channel 1 in the client's own container throughout. So the 20-minute deadline is a hard,
reproducible timer on the connection object, and the ALC/position traffic does not
touch it.

**The candidate patch was later refuted.** With the five bytes at `0x141004230` NOPed and read-back verified, the client still exited to the main menu at 20 min 0.4 s after spawn. The queued delegate/backtrace remains useful evidence, but this callsite is not the fix. Trace the actual caller/delegate path; see `exit_patch_0x141004230_refuted_20261011` and the current `STATUS.md`.

---

## 5. What is stable right now (so the night was not wasted)

The run at 06:39 rendered a possessed-player scene and kept REP transport alive during its observation window; it did not pass the connection-UX, movement, or 20-minute session-lifetime gates:

* `player spawn succeeds, in game` at 06:39:50;
* the world rendered with a possessed player, NPCs, and HUD. That screenshot proves rendering/possession only; it does not prove active physics, movement, ALC health, or a session beyond 20 minutes;
* server side: 25 027 outbound datagrams, 21 610 inbound, 1 218 heartbeats,
  1 218 input responses, 89 position replies, 2 start-movement;
* client side: `transportError` 0, `OnLocalNetworkConnectionWarning` 0,
  `ValidationError` 0, `Failed to unmarshal` 0;
* REP transport counters were clean in this window; the HUD warning remained red, movement was not demonstrated, and the separate 20-minute exit still occurred.

This established a transport/rendering baseline only. The red HUD cable remained visible, movement was not proven, the 20-minute exit persisted, and the attempted patch was later refuted.

---

## 6. Tools created for the historical runs (check current git status)

| tool | what it does |
| --- | --- |
| `reverse/probes/client/frida-20min-exit.py` | backtraces the self-exit decision |
| `reverse/probes/client/frida-exit-patch.py` | NOPs the exit call + watches the session |
| `reverse/probes/client/frida-patch-exit-once.py` | one-shot apply/restore of that patch |
| `reverse/probes/client/frida-aa8-watchpoint.py` | hardware watchpoint on the "last response" stamp |
| `reverse/probes/client/frida-aa8-catch.py` | page-level access monitor + vtable dump of that object |
| `reverse/probes/client/frida-position-consumer.py` | counts calls into the position reader |
| `reverse/probes/client/frida-type-resolver.py` | counts resolved wire types by GUID (with typeIndex names) |
| `reverse/probes/client/frida-hud-thresholds.py` | reads the two live HUD thresholds + the ALC stamp |
| `scripts/night-run.py` | one unattended A/B run: probe + drive + screenshot + summary JSON |
| `scripts/corpus-contains.py` | "which corpus function contains this VA" for backtrace frames |

---

## 7. Current plan, in priority order

1. **Connection gate:** on a fresh client, capture the real HUD indicator, both ALC objects' `+0xAA0`/`+0xAA8`, and REP logs on the same clock. Trace the producer/consumer that should open the ALC door. Input-response messages and `StartMovementCommunicationMsg` have already failed to open it. Change one evidence-backed behavior per run. Pass only when the actual red HUD warning clears, REP has no transport error, and the client remains in-world beyond 20 minutes; then repeat for 30 minutes and a 2-hour soak.
2. **Movement diagnosis:** attach before world entry and read the local player's transform, body/controller activation, and the consumer of channel-1 `0x635` while pressing and releasing W. Do not use screenshot-diff ratios as a movement result.
3. **Position application:** trace why reliable 4216 is decoded but its RMI dispatch cannot find `targetLocalId`/`IPositionReceiver`. Do not change the payload or container until the target binding is identified.
4. **Movement pass:** require a measured transform delta while W is held, no continued delta after release, and a successful client/server movement exchange. Then add turning and collision checks and server-authority validation.
5. **Session lifetime:** trace the queued-delegate/caller path behind the exact 20-minute menu return. The patch at `0x141004230` did not prevent it.
6. After every attempt, append the exact build, config, run/capture IDs, directly observed values, inference, validation, side effects, and failed hypotheses to the atlas before handing work off. Update `STATUS.md`, `HANDOFF.md`, and the public roadmap when the evidence changes.

## 8. Historical reproduction recipe (not the current acceptance recipe)

```powershell
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'  # optional historic lever; not an ALC/HUD fix
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'
python az.py dev
python scripts/patch-dtls-disk.py apply
python scripts/night-run.py --tag <name> --probe frida-position-consumer --minutes 25
python scripts/patch-dtls-disk.py restore
```
