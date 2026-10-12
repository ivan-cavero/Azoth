# Live status

## 2026-10-12 (cont. 4) — the live player entity's 126 components are now named, and the physics claim does not reproduce

**The component resolution bug is fixed and the list is complete.** Every component of the live
local-player entity is now dumped and named. The old probes rejected **126/126** components
because they checked `inCode(vtable)` — on this build a component's vtable lives in `.rdata`
(`r--`) while the function pointer inside it lives in `.text`, so the check must be on the
resolved **function pointer**, never the vtable. With that fixed, run `comp-083309` resolved
**126/126 with zero failures** (`bad: nullComp 0, badVtblPtr 0, badSlot0 0, nullType 0, exc 0`).
Probe: `reverse/probes/client/frida-player-components-full.py`. Atlas:
`player_entity_component_list_measured_20261012`.

**The position plumbing is on the entity:** `PlayerPositionTrackingComponent` (index 95, GUID
`62620B33-6F37-418B-9C4F-62AD6058D54D`), plus `CharacterComponent`, `Transform`,
`TraversalComponent`, `CameraLockComponent`, `PlayerInputFiltersComponent`,
`MotionParameterSmoothingComponent`, `PlayerAOIComponent`, `SpectatedPlayerComponent`,
`SpectatorModeComponent`, `SkinnedMeshComponent`, `FootstepComponent`, `PlayerSaveData` and
more (36 of the 126 GUIDs have no name in the atlas registry).

**`CharacterPhysicsComponent` and `GameRigidBodyComponent` do NOT reproduce on the live
entity.** At ~4 s after spawn, neither is in the 126-component list, and asking the CLIENT'S
OWN lookup `FUN_1413fb700` for both GUIDs (trying both byte orders) returned `found=False`
while the controls `Transform` and `CharacterComponent` returned `True`. That is the same
method the committed record `local_player_components_step0_20261010` used, with the opposite
result. **This is recorded as an unresolved disagreement, not a retraction:** the dump is one
instant ~4 s after spawn and the client crashed ~3 s later, so whether the client adds physics
later is unknown. The deciding experiment is to re-dump the same entity at spawn+4 s, +30 s and
+2 min in one session while logging every ADD (`FUN_1413789c0`). Atlas:
`physics_components_absent_on_the_live_player_entity_20261012`.

**Crash attribution corrected: Frida itself is a crash source.** The Windows Application log
names the faulting module, and the crash that ended `comp-083309` was in
**`frida-agent.dll_unloaded`** at offset `0x9c7e0` — i.e. the instrumentation, not the game
logic. Other recent crashes are `ntdll.dll` at `0x1662b7` (twice) and `0xc4a0f`. Rule for the
next runs: attach as late as possible (at character select, via `private-run.py --no-play`),
prefer hooks-only probes, and treat a death as an invalid attempt unless the faulting module is
`NewWorld.exe`. Atlas: `frida_agent_unload_is_a_crash_source_20261012`.

## 2026-10-12 (cont. 3) — the player position is now measured directly: W does NOT move it

**Movement is now measured with the client's own instrument, not with offsets or screenshots.**
The client ships `nw_getPlayerPosition` ("print player position to the screen"). Its handler
`0x141015b30` calls the accessor **`FUN_140fddfa0(&holder)`** and prints
`*(float*)(holder+0x14c)`, `+0x15c`, `+0x16c`. That is the local player position in the
client's own format, and the sibling command `teleport` (handler `0x141020a40`) reaches
`FUN_140fbf3b0`, so the client can also set its own position. New probes
`frida-player-position.py` and `frida-position-validate.py`; the latter **calls the client's
own command handler** and watched its printer fire (0 → 1), which confirms the accessor is
the client's own position rather than a guessed object. Atlas:
`player_position_accessor_and_console_commands_20261012`.

**Measured, run `rcv2-073512` (in-world, possessed):** the position was sampled at 0.2 s and
**667 of 667 samples were identical** — `(9343.6416, 2786.7327, 87.538)` — across a 136 s
window containing a **10 s W hold** and a 4 s S hold as a control. The instrument was live
(RMI dispatch counter 124) and the input did reach the game: the world server logged
**8184 app-data events carrying 7804 channel-1 records** in the same window. So: input
leaves the client, the position never changes, and no screenshot or byte-diff is involved.
This satisfies the negative half of the movement acceptance criterion. Atlas:
`w_does_not_move_the_player_measured_with_the_client_accessor_20261012`.

**Why, in two parts — both newly measured.**

1. **The `ActorMover` family is NOT locomotion.** Its surviving strings are a server-side
   hub-migration protocol: `Sending CommitMovement for actor`, `Destination hub timed out
   before receiving CommitMovement or AbortMovement…`, `DelayMigrationsMsg`,
   `MoveActorToHubMsg`. So `StartMovementCommunicationMsg` was the wrong lever from the
   start, consistent with it changing nothing when sent reliably on channel 0. The real
   plumbing is `PlayerPositionTrackingComponent` (GUID `62620B33-…`), `PositionInTheWorldComponent`,
   `PositionalTicketingComponent`, `CameraPositionListener`. Atlas:
   `actormover_is_hub_migration_not_locomotion_20261012`.
2. **The receiver is never created.** `frida-position-receiver` ran for a whole session
   (spawn 07:38:56, still in-world 07:57): **`installer=0` and `register=0` in every
   sample**. The installer `0x143f983d0` is the only site in the image referencing the
   interface vtable, so over a full login + world entry + 18 min in-world the client never
   creates or registers an `IPositionReceiver`. No target id can work because the object
   does not exist. Atlas: `position_receiver_never_created_in_a_full_session_20261012`.

**The 20-minute exit did not arm (replicated).** With `AZOTH_CHUNK_GAP_MS=4` the session
passed 22 min 12 s with `ActorContainerDisconnect` 0 and `exiting to main menu` 0 — a second
independent gap-4 run agreeing with `exitval2-202053` against the gap-20 run that armed at
exactly 20:00.398. Atlas: `exitA_gap4_replication_20261012`. The HUD cable was RED in every
sample; no run has yet reached the 30-minute acceptance.

**Next experiment.** Build the position work on `PlayerPositionTrackingComponent` /
`PositionInTheWorldComponent` (not `ActorMover`), and find which client object would create
the `IPositionReceiver` instance — the object graph is incomplete for several client facets,
not only this one. The accessor now makes every subsequent movement claim measurable, and
`nw_findLocalEntity` / `nw_getPlayerHealth` give the same treatment to other questions.

## 2026-10-12 (cont. 2) — the receiver is data-driven; a repeatable ntdll crash blocks the world

**The IPositionReceiver machinery is fully mapped, and it is data-driven.** The interface
vtable `0x1482eb160` is referenced by exactly **one** site in the whole image: the installer
`0x143f983d0` (`lea rax,[0x1482eb160]; mov [r8],rax`), which is reached as slot **+0x28** of
the family's base vtable `0x1482ea4e8`. That base vtable's slot **+0x20 is `0x140294860` =
`ret 0`** (returns null), which is why the delivery can never answer on a base-typed object:
`FUN_143f97bf0` does `q = target->vtable[+0x20](target, IPositionReceiver_guid)`. The
interface is registered by name by `0x143f98300`. Neither the installer nor the register
function has a direct caller, so both are invoked through the AZ reflection descriptor —
**the instance creation cannot be found by following xrefs and has to be observed.**
Atlas: `ipositionreceiver_vtable_layout_20261012`, `az_interface_decoupler_mechanism_20261012`.

**The blocker is reframed: our replay delivers to unbound client facets generally.** In
`exitval-194552` the 13041 `facet target ID couldn't be found` errors are 13012 position
replies **plus 23 `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`** (wire 7048)
plus time/phasing/notification ones. So the replay itself sends messages to client facets
that are not bound, independently of the position reply: this is "the client's local-player
object graph is incomplete", not "we picked the wrong message". Atlas:
`replay_sends_to_unbound_client_facets_20261012`.

**New instrument, verified working; the decisive count was NOT obtained.**
`reverse/probes/client/frida-position-receiver.py` hooks the installer, the register-by-name
and the delivery (control), and reads the AZ reflection registry at `0x14a313ff8`. In run
`rcv-070042` the hooks installed and fired, but **the client crashed during login before
`player spawn succeeds`** with `0xc0000005` in `ntdll.dll` at **offset `0x1662b7`** — the same
signature that ended `exitval-194552`, and different from the older Frida-startup crashes.
Both `0x1662b7` runs had a read-only Frida probe attached (correlation, not proof: `mvB`
and `mvD` also had probes and did not crash there). So the current failure mode blocking a
30-minute session includes a repeatable `ntdll+0x1662b7` access violation. Atlas:
`position_receiver_probe_and_ntdll_crash_signature_20261012`.

**Next experiment.** Run `frida-position-receiver` in a session that actually reaches the
world, and read the installer/register counters: if they stay 0 for a whole session the
client never creates the receiver and the missing piece is upstream in the object graph; if
they fire, the recorded return address names the creating code. Because the crash interferes,
run it without any other probe attached, and treat a crash before `player spawn succeeds` as
an invalid attempt rather than a result.

## 2026-10-12 (cont.) — the position reply's target was wrong, not the interface; the client's input stream is identified

**Three corrections that change how the movement work should be read.**

1. **The client's channel-1 stream is `ActionListComponentServerFacet_ReceiveInputFromClient`**
   (wire 1589 / `0x635`), not an unnamed state stream. Measured on the whole session:
   **19676/19676** channel-1 records have a valid `[crc32][len]` container, all with
   target = the full 16-byte actor id `1a954abc4b3185bfbe37c3d8592618e0` and type
   `0xC35`. So the client streams its ALC input to the server ~20×/s and the input
   direction already works. Evidence: `input_stream_is_action_list_facet_call_20261012`.
2. **The `0x1096`/`0x1097` "input response" is a misnomer**: they are
   `TimeComponentClientFacet_SyncTimeChange` / `SyncDayPhase`. So `AZOTH_REPLAY_INPUT_RESPONSE`
   replays **time sync** messages, and the recurring `2 × SyncTimeChange + 2 × SyncDayPhase`
   facet errors are those. Evidence: `wire_type_names_from_binary_20261012`.
3. **My previous "dispatch fixed" result was a false fix.** The blob that makes the
   dispatch succeed (`93a3e477cb5fd51e`) is the client's **`TimeComponentClientFacet`**
   local id — the target the capture's own time-sync messages use. Re-addressing the
   position reply there turns a loud failure into a silent wrong-object delivery: the
   dispatch succeeds (642/642, 0 facet errors) but the position goes to a time-sync
   facet, so `FUN_143f97bf0` still returns 0. Evidence:
   `position_reply_timecomponent_target_is_a_false_fix_20261012`.

**The interface is implemented; no instance is bound.** The whole chain is now located by
bytes: the delivery queries `target->vtable[0x20]` with the GUID from `FUN_143fb2b90`
(0x143f97c0a-0x143f97c4c); `FUN_143fadd00` is that QueryInterface (returns `this` on a GUID
match); the receiver's vtable is **`0x1482eb160`**, installed by the 6-byte function at
`0x143f983d0`; the interface is registered by name by `FUN_143f98300`; the RTTI descriptor
is `IPositionReceiver` at `0x1482ea920` with GUID
`{17C00FC6-074F-47EB-9640-9743D890ED6F}`. The blocker is that **no client-side RMI target
is an instance of it** (37063 targets, 225 distinct vtables, 0 positives). Evidence:
`ipositionreceiver_implementation_located_20261012`,
`message_interface_map_from_pdb_strings_20261012`.

**`StartMovementCommunicationMsg` is not the trigger — measured.** Sending it **reliably on
channel 0** (the framing fix: the earlier attempt was unreliable on channel 1, which the
client never decodes) still binds no receiver and the actor-id reply still fails: **1581**
facet errors for `ReceivePlayerPositionClientMsg`. The body was never the problem
(20 bytes, verified against the client's own reader `FUN_146a55240`). And the client never
sends `0x2D6` itself (1144 channel-0 records enumerated; absent). Evidence:
`start_movement_reliable_ch0_does_not_bind_receiver_20261012`.

**Next experiment.** Find what constructs an instance of vtable `0x1482eb160` and registers
it as a client-side RMI target, and what tells the server its local id. The client's own
outbound messages address a 16-byte target that begins with the actor id because they call
a *server* facet, so the actor id being the client's outbound target does not make it a
valid client-side target for our reply.

## 2026-10-12 — dispatch fixed by re-addressing the reply; the blocker is now the interface binding

**Movement, step 1: SOLVED and measured.** `AZOTH_REPLAY_POSITION_REPLY_TARGET` (the
re-addressing lever added last session) removes the `facet target ID couldn't be found`
failure completely. Same reply, only the target blob changed from the actor id to
`93a3e477cb5fd51ebf85314bbc4a951a`:

| run | target blob | dispatch of that id | facet errors for 4216 |
| --- | --- | --- | --- |
| `exitval-194552` | actor id | 0 / 601 | 13012 |
| `mvB-020002` | capture input-response blob | **642 / 642** | **0** |

The delivery path itself also succeeds (260/260 non-null). Evidence:
`position_reply_target_fixes_dispatch_20261011`.

**Movement, step 2: the remaining blocker is precise.** `FUN_143f97bf0` still returns 0:
the target it receives does not answer the `IPositionReceiver` interface query. A scan of
all **37063** registered targets, grouped by object vtable (**225** distinct vtables) and
queried through the client's own GUID getter `FUN_143fb2b90`, found **no registered target
that answers that interface**. So no target id can work: the interface has no bound
instance, which is the same open question as the ALC conversation. Evidence:
`position_target_scan_no_binding_20261011`.

**Movement, step 3: instrument built, position offset still unknown.** New probe
`frida-movement-state.py` resolves the live player entity's `Transform` and
`GameRigidBodyComponent` through the client's own lookup `FUN_1413fb700`. A 4 s W-hold
produced zero changed words in the transform component's first 0x100 bytes — but reading
that object shows a pointer/counter header, not floats, and no plausible position float
triple exists in it or in its first writable pointer. **That zero-change result is a
measurement of the wrong bytes and proves nothing about movement.** Next step: trace the
client's own transform accessor instead of guessing offsets. Two invalid resolution
methods are recorded so they are not repeated. Evidence:
`player_entity_transform_readable_but_position_offset_unknown_20261011`.

**Connection / session lifetime: the 20-minute exit is armed by the replay gap.**
One-variable A/B, no Frida in either run:

| run | `AZOTH_CHUNK_GAP_MS` | replay | 20-min exit |
| --- | --- | --- | --- |
| `exitA-gap20-012032` | 20 | 29 s | **fired at 20:00.398** |
| `exitval2-202053` | 4 (default) | 10 s | did not arm (session ended 26:33 by a REP disconnect) |

And the corrected patch is now **exercised**: in `exitA-gap20-012032` the delegate ran
(`CGame::ActorContainerDisconnect` logged) and the patched call at `0x14100425F` was
skipped — `exiting to main menu` 0, `Cleanup()` 0, where the pre-patch runs logged both.
**It is not a session fix:** the same delegate tears the connection down at
`0x141004230` *before* the patched call, so the client stopped sending traffic at
20:00.398 (zero server-side events after that; the world on screen at 01:54Z was a frozen
frame). To survive past 20 minutes the **arming** must be prevented, not the exit call.
Evidence: `exitA_gap20_run_outcome_20261011`,
`chunk_gap_decides_the_20minute_arm_20261011`.

**Next three experiments.**

1. Find what binds an `IPositionReceiver` (same question as the ALC conversation); no
   target id can work until something does.
2. Trace the client's own transform accessor, then re-run the W-hold measurement against
   the real position bytes.
3. Arm-side fix for the 20-minute path: hook the enqueue (`FUN_14107fb40`, the
   deferred-action queue drain) rather than patching the exit, since gap 4 merely moves
   the failure to a 25-26 minute disconnect.

## 2026-10-11 (late) — the 4216 dispatch blocker is a wrong target id; the 20-minute exit is conditional

**Movement.** The `RMIDispatch: The facet target ID couldn't be found` blocker for wire
4216 is now measured, and it is **not** a missing facet type. The client's RMI target
registry holds **37063** entries; the actor id the server's position reply carries
(`1a954abc4b3185bf`) matched **0 of 601** lookups, while the 16-byte blob the capture's
own input-response messages carry (`93a3e477cb5fd51ebf85314bbc4a951a`) matched
**136 of 136** in the same session. So the reply is addressed to a target the client
never registered. New probe `reverse/probes/client/frida-rmi-targets.py` dumps the
registry (capacity, every key, each target's object and vtable). New env lever
`AZOTH_REPLAY_POSITION_REPLY_TARGET` re-addresses the reply without a code edit.
Evidence: `rmi_target_registry_measured_20261011` and
`rmi_dispatch_facet_target_registry_20261011` in
[`client-functions.json`](research/atlas/client-functions.json).

**Connection / session lifetime.** The corrected exit call site `0x14100425F` is
byte-verified statically (`exit_delegate_call_site_verified_20261011`), but it is **not
yet validated live**, and the exit-to-menu path did not fire in **three consecutive
patched runs**: `exitfix-161219` (stopped 84 s in-world, cause unresolved),
`exitval-194552` (25 min 06 s, ended by an access violation `0xc0000005` in `ntdll.dll`
~40 s after a read-only Frida probe detached), and `exitval2-202053` (26 min 33.6 s,
ended by a **client-side REP disconnect**: `CGame::ActorContainerDisconnect` +
`Disconnected from REP` + `InGame -> Disconnected`, `transportError` 0, then the client
returned to the frontend and re-logged in). `CGame exiting to main menu` and `Cleanup()`
are absent from all three, so the delegate never reached the patched call. Earlier runs
left the world at exactly 20:00.4. So the 20-minute path is **conditional** and the
current failure mode is a **~25-27 minute client-side disconnect or crash**, not the
menu timer. Method note: `FUN_146420610` has 11 callers, so its log line marks *some*
caller, not the delegate; only its absence is decisive. Full record:
`exitval_194552_run_outcome_20261011`, `exitval2_202053_run_outcome_20261011`,
`exit_to_menu_path_not_reproduced_20261011`.

**Next experiment (one variable).** Baseline with `AZOTH_CHUNK_GAP_MS=20` and nothing
else changed: that is the best-supported difference (the runs that exited at 20:00.4
used 20 ms; both recent runs used the 4 ms default) and it decides both whether the
exit returns at 20:00 and whether the patch is exercised. Then re-address the position
reply with `AZOTH_REPLAY_POSITION_REPLY_TARGET` and measure whether the dispatch
succeeds and the local transform changes. Keep Frida attaches out of the baseline runs.

Also recorded this session: `.azoth/night/runs/exitfix-161219` (the previous run, never
analysed) stopped 84 s in-world with no exit line; its world log is preserved as
`.azoth/logs/world.log.exitfix-161219`.

## 2026-10-11 — transport survives; visible connection and movement remain open

**The player still cannot move. A previous version of this section claimed the
opposite and was WRONG** (retracted: `retracted_movement_claim_20261011` in
[`client-functions.json`](research/atlas/client-functions.json)). The claim rested
on a screenshot diff, and `scripts/bmp-diff.py` computes
`motion ratio = mad(shift 0) / best_mad(±24 px)`; a real camera translation makes
the best shift match *better* than no shift, i.e. ratio **> 1**. The W-hold pair
gave zero-shift mad 37.21 and best mad 39.46 — the best shift was *worse* than no
shift — so 0.94 means the scene changed but **did not translate**. A screenshot
diff cannot establish movement.

**What is solid (non-visual, binary):**

- **The Carrier `MF_RELIABLE` flag is required for the wire-4216 decoder path.** Unreliable
  (`flags 0x20`) the client resolved 3418 messages across 90 types with 4216
  **absent** and the reader at **0** calls. Reliable (`flags 0x21`) the same stack
  resolved index 4216 **212** times and the reader ran **212** times, 1:1.
- **The 4216 reader is reached; subsequent RMI dispatch attempts fail.**
  `Game.log` logs 103 times:
  `RMIDispatch: The facet target ID couldn't be found when trying to dispatch the
  RMI message. {"targetLocalId":1915519389091857855,"messageType":"ReceivePlayerPositionClientMsg"}`.
  That is the logged form of the static prediction that a bound
  `IPositionReceiver` is required (`FUN_143f97bf0` looks the interface up by GUID
  and returns 0). The message reader is reached, but the position is **not
  applied**. This does not establish movement.

**Next decisive measurement:** read the local player's own transform (position
vector) live while W is held — not screenshots. That is the only thing that can
settle "does the player move".

Historical snapshot: 2026-10-11 afternoon (later measurements below supersede the early 4216 interpretation).

## Historical afternoon snapshot (2026-10-11; later results below supersede it)

This snapshot is retained for experiment history. Later runs and direct probes below supersede its early interpretation of 4216 and the HUD cable. Evidence is in
[`research/atlas/client-functions.json`](research/atlas/client-functions.json)
(`alc_pointer_never_opens_live_20261011`,
`wire4216_never_resolved_live_20261011`,
`exit_patch_0x141004230_refuted_20261011`,
`start_movement_does_not_open_alc_20261011`).

- **Item 1 — the ALC pointer never opens.** A new probe reads BOTH classes that
  keep a field at `+0xAA8` (the HUD object `FUN_14486c740` and the connection
  object `FUN_1449309b0`). `+0xAA0` stayed **0** on both for the whole session,
  and the HUD stamp moved once (at `replay-complete-quiet`) then froze. Sending
  `StartMovementCommunicationMsg` (0x2d6) did **not** open it either. So the door
  is **upstream of the ALC module**, not inside it. No tested message has opened it; the missing handshake producer remains to be identified. A server-side handshake is the leading inference, not a demonstrated implementation. The client does stream input (23 819 channel-1 records).
- **Item 2 -- reliability opens the 4216 decoder path; it does not solve movement.**
  With `flags 0x20`, 700+ replies produced **0** resolutions and reader calls.
  With `flags 0x21`, the resolver and reader ran **212 times**, but later
  `Game.log` showed 103 RMI dispatch failures because `targetLocalId` has no
  facet target. This is a decoder gate only; neither application nor movement
  is established. The earlier screenshot-based movement claim was retracted.
  See `position_reply_now_decoded_but_not_applied_20261011` and
  `retracted_movement_claim_20261011` in the atlas.
- **Item 3 — the 20-minute exit patch is REFUTED.** With the patch applied and
  byte-verified (`e8dbc34105` -> `9090909090` at `0x141004230`), the session still
  died at **20 min 0.4 s** after spawn with a clean `exiting to main menu` +
  `Cleanup()`. The five bytes were still NOPs afterwards. The timer is real; that
  call site is not the path it uses.
- **Server bug fixed (it caused an earlier transport failure before the separate menu exit).**
  `on_app_data` parsed the raw (still LZ4) body of envelope `0x81` as Carrier
  records; garbage produced channel 4 and `parse_datagram`'s guard (`channel > 4`
  while `per_seq` holds four slots) raised `IndexError`, the loop dropped the peer
  and the client logged `transportError 4` ~18.7 min in. Now `on_app_data`
  decompresses first and the guard is `channel > 3`; regression test added.
  **120 world tests pass.**

Updated: 2026-10-11 (overnight session; full report in
[`research/docs/NIGHT-REPORT-2026-10-11.md`](research/docs/NIGHT-REPORT-2026-10-11.md)).

## Overnight 2026-10-11 — what changed

- **The red HUD cable tracks stale ALC response age.** The measured color
  thresholds are amber after 2 s and red after 15 s;
  `javelin.alc-server-timeout-for-input` is one 2000 ms client cvar, not the red
  threshold itself. The HUD compares `now` with its `+0xAA8` stamp. Live probes
  found the ALC door `+0xAA0` closed and the HUD stamp stopped advancing after
  initialization/replay activity; static analysis found no recurring writer in
  this build. REP logged no transport error while the icon remained red. This is
  stale ALC response state, not a REP disconnect; the handshake producer remains
  unknown.
- **The client's record container is decoded**: every non-chunked DATA record on
  channels 0 and 1 is `[u32 BE crc32][u32 BE len][16-byte target][00 01][type][body]`
  (40 279/40 279 channel-1 records and 285/294 channel-0 records verified). The
  server uses the capture's `[vlq32 len]` form instead.
- **The client streams exactly one type**: channel 1 carries only type `0x635`
  (17 912 records in one session). Its channel-0 traffic is `0x15d` plus typed
  requests.
- **The separate ~20-minute return-to-menu path is still open.** A live trace
  observed a queued delegate and a teardown candidate at `0x141004230`
  (`exit_to_main_menu_delegate_chain`), but patching that call did not prevent
  exit: the client returned to menu at 20 min 0.4 s. The candidate is refuted as
  a fix; trace the actual delegate/caller before changing code.
- **Historical container result (superseded for channel-0 reliable).** An earlier
  A/B got zero reader calls for the tested client-container/channel variants
  (`position_reply_containers_refuted_20261011`). A later run with reliable
  flags `0x21` reached the 4216 reader 212 times, then failed RMI facet-target
  dispatch. The current blocker is application binding, not a proven container
  failure.
- **Trap fixed for future runs**: `python az.py dev` returns before the gateway
  binds :8080, and launching inside that window makes Caddy answer 502 for the CMS
  manifest; the client then stalls with `Auth manager does not exist`. `night-run.py`
  now waits for the manifest to return 200 before it launches.

Updated: 2026-10-09 (overnight session). Exact function evidence is in
[`research/atlas/client-functions.json`](research/atlas/client-functions.json);
the consolidated wire reference is
[`research/docs/JAVELIN-PROTOCOL.md`](research/docs/JAVELIN-PROTOCOL.md) and the
message table is
[`research/atlas/javelin-messages.json`](research/atlas/javelin-messages.json);
what the client expects from the server, phase by phase, is
[`research/docs/SERVER-CONTRACT.md`](research/docs/SERVER-CONTRACT.md); how to
bring up and patch a private run is
[`research/docs/PRIVATE-CLIENT-RUNBOOK.md`](research/docs/PRIVATE-CLIENT-RUNBOOK.md).

## Active objective

Deliver a usable in-world session with both **visible connection health** and
**controllable player movement**. Entry, rendering, and possession reproduce;
REP transport survived a 2 h 06 min run, but the user still sees the red ALC/HUD
warning and the client has a separate 20-minute return-to-menu path. Movement is
not solved and its cause is not yet known.

## Confirmed

- **World entry and possession work (2026-10-07).** With the runbook sequence
  the world renders and the player is possessed: `Initialize()` without
  `Cleanup()`, `player spawn succeeds, in game`, and `InGame`. This does not
  establish that the player's physics/controller is active.
- **REP transport survived 2 h 06 min (2026-10-10); user-visible connection is
  still open.** The run had `transportError` 0 and `disconnected from REP` 0,
  while the red ALC/HUD warning remained visible. The ALC input stamp stops
  updating and the ALC door stays closed. A separate client return-to-menu path
  still occurs around 20 minutes. Keep these results separate in reports.
  1. **The REP watchdog heartbeat no longer waits for the replay.** This activity-warning clock is separate from the red ALC/HUD stamp. The `0x15d` heartbeat
     and the `0x1096`/`0x1097` input response both gated on the replay queue being
     empty, but the replay is ~1090 Carrier chunks and needs ~22 s at
     `AZOTH_CHUNK_GAP_MS=20` — inside the client's ~27 s watchdog. The session log
     had **zero** `heartbeat` and **zero** `input-response` events. They now run
     concurrently with the replay, which is what the capture shows the real server
     doing. The state stream still waits: it re-applies the same captured bundles,
     and double-applying state is not idempotent client-side.
  2. **16-bit wire fields now wrap.** The server's envelope sequence was unmasked,
     so once `next_out_seq` passed 65535 the keepalive raised
     `OverflowError: int too big to convert` and stayed dead for **two hours**
     (7395 consecutive tick errors). Every 16-bit field now goes through `_u16()`,
     and a `tick-error` logs a traceback so a repeating error names its function.
- **CORRECTION to the warning count above, measured 2026-10-10 on the documented
  configuration.** The `OnLocalNetworkConnectionWarning` **1** figure does not
  reproduce: two live runs on `AZOTH_CHUNK_GAP_MS=20` logged a burst of **104** and
  **116** warnings, starting ~2 s after the spawn and stopping when the replay
  drained. The server log shows why — `replay-chunk` ran 19:30:40Z..19:31:09Z (29 s),
  `replay-complete-quiet` fired at 19:31:09Z and the **first `heartbeat` was also
  at 19:31:09Z**: not one ping during the whole replay.
  `PeerSession._post_replay_started()` returned `self.greetings_after_replay`, which
  is set only when the replay queue **drains**, so the gate-8f concurrency fix was a
  silent no-op. It now returns `self.v3_responded`, and the fix is verified: **20
  heartbeats fire before the drain** (was 0). See
  `post_replay_predicate_regression_20261010` in
  [`client-functions.json`](research/atlas/client-functions.json).
  **For the Game.log activity-warning counter (not the left-edge ALC/HUD cable), the measured 2026-10-10 result is that the burst tracks REPLAY DURATION.**
  While the replay is still streaming the client has not re-stamped its REP activity
  watchdog clock, so it warns every interval until the replay finishes — the burst lasts
  exactly as long as the replay. Four paired runs, one variable at a time
  (`scripts/measure-run.py`, raw rows in `.azoth/logs/ab-runs.jsonl`):

  | `AZOTH_CHUNK_GAP_MS` | activity stream | replay | warnings | transportError |
  | --- | --- | --- | --- | --- |
  | 20 | off | 76 s | 80 | **1** + disconnect |
  | 20 | **on** | 29 s | 82 | 0 |
  | 8 | off | 15 s | **0** | 0 |
  | unset (default **4**) | off | 10 s | **0** | 0 |

  So: in this replay-duration/Game.log-warning A/B, the type-`0x1b88` activity
  stream **did not help** (80 vs 82 — hypothesis
  refuted); 32 heartbeats before the drain **did not save** the 20 ms run; and the
  runbook's `AZOTH_CHUNK_GAP_MS=20` is slower than the code's own default of 4 ms
  while sitting right on the client's ~27 s watchdog. See gate 8g in
  [`PRIVATE-CLIENT-RUNBOOK.md`](research/docs/PRIVATE-CLIENT-RUNBOOK.md).
  **Unresolved trade:** a fast replay is warning-free but one run logged a
  `Cleanup()` ~3 min in; a slow one is calmer but risks the 27 s kill. The next
  measurement is *what makes a fast replay unstable*.
- **The server now emits on its own clock.** Every periodic emitter used to be
  called from `on_app_data` (once per inbound datagram), so server output scaled
  with client input: measured `Pearson(inbound, outbound) = 0.995`, peak 286
  datagrams/s, amplification 3.4:1. `PeerSession.tick()` now runs from the UDP
  loop at `TICK_HZ` (50) whether or not a datagram arrived. After: Pearson
  **0.180**, amplification **0.96:1**, peak **99/s**, `v3-registered` 8 -> **1**.
  `TestAuthoritativeTick` fails if a periodic emitter is ever called from
  `on_app_data` again.
- **Three server defects that made the loop stall itself are fixed** (each could
  cause a REP `transportError 4`/disconnect; those do not by themselves explain
  the separate ALC/HUD cable): the event log reopened a ~90 MB file per
  event (measured 27 s of silence under a 287-record burst); every ACK was a
  separate datagram (1:1 with inbound); and the post-replay heartbeat was
  retried to its 6-try cap (1106 heartbeats produced 5437 resends, 46% of all
  outbound traffic).
- **Private-run gates 1-8b** (see the runbook). Three fail silently: Caddy CA
  trust, the DTLS pin, and the server settings below.
  - Gate 5 (black screen) = the ClientContext predicate.
  - Gate 6 (no player) = server env `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`.
  - `AZOTH_REPLAY_INPUT_RESPONSE=1` is not a fix for the measured ALC/HUD
    warning; the icon remained red with input responses active.
  - The default replay gap is 4 ms; 20 ms was slower and had worse watchdog
    results in the recorded A/B. Do not treat 20 ms as a solved gate.
  - Gate 8b (resend storm) = `AZOTH_RESEND_INTERVAL_S=1.0`.
- **The launcher was dead on PowerShell 5.1** (`$PSScriptRoot` inside a `param()`
  default), and `az.py`/`private-run.py` both use `powershell.exe`, so the whole
  documented run path was broken. Fixed 2026-10-09.
- **The protocol is now decoded at the container level** (2026-10-09), with
  tests rather than prose:
  - The **prefix varint** every typed message and bundle field starts with.
    `services/world/src/azoth_world/javelin/varint.py`; 137/138 captured message
    types round-trip.
  - The **type-0x08 StateBundle** body, byte-exact: 78 of 79 captured bundles
    consume their body exactly. `javelin/bundle.py`.
  - The **message registry**: all 144 message types with GUID and wire type,
    `research/atlas/javelin-messages.json`. All 12 movement wire types reproduce
    from two independent derivations.
  - The **replication gate**: a bundle is accepted only when its instance id
    matches and its counter exceeds the client's high-water.
- **Warnings in a clean session are few and all benign**: 26 x Slice transform
  (0-component `remoteplayer` slices), 25 x RMIDispatch facet-not-found, 1 x
  `RequestGetPlayer: empty characterId`, 1 x benign physics note, 1 x
  `XDllSingleton already instantiated`.
- Input delivery is verified: scan-code `SendInput` reaches the client, mouse
  look rotates the camera, and the UI consumes keys. Holding W produced no
  movement-family message in the sampled session. The old screenshot-diff ratios
  are not a movement measurement; read the live player transform directly.
- **The client is confirmed to consume our post-replay traffic (2026-10-10).**
  Hooking the type-resolution function `FUN_1461acfe0` on a live session shows
  the client resolving exactly three type ids in a repeating cycle, and they are
  the three messages the server sends after the replay: index 349 (`0x15d`,
  PingMsg — the heartbeat), and 4246/4247 (`0x1096`/`0x1097` — the input
  response). This proves those typed messages are resolved; it does not prove
  that the real HUD warning clears or that the ALC input stamp refreshes.
  **Historical fragment-reader doubt superseded:** later direct hooks on
  `FUN_146af20d0`/`FUN_146af2340` measured record and nested-fragment reads, and
  the record/fragment grammar is documented above. Unknown per-type payload
  codecs remain open.
- **The `inject` lever is validated end to end.** A type-0x08 StateBundle built
  from scratch by `javelin/bundle.py` was accepted by the live client with no
  error, which is independent proof that the container layout is right. A
  `StartMovementCommunicationMsg` (`0x2d6`) with an empty body was also accepted,
  proving the type and framing. **Negative result:** a bundle carrying an unknown
  fragment `type_index` is dropped *silently*, so the client log is not a usable
  signal for "does the client know this fragment type" — future codec work needs a
  Frida hook or an observable state change instead.
- Tests most recently documented: **120 world**, **24 gateway**.

### Objective: visible connection and controllable movement

Keep the immediate slice focused on two user-visible gates: clear the real ALC/HUD
warning and prove the player transform changes with W. The shared replication
mechanism matters after a measurement shows which state or message is missing; do
not assume that adding generic PhysicsTrait codecs will fix movement. The sequence
and acceptance criteria live in [`docs/ROADMAP.md`](docs/ROADMAP.md).

**The corrected component measurement is complete:** the live 126-component
player entity contains `CharacterPhysicsComponent` and `GameRigidBodyComponent`,
and the client's own lookup finds both. The older claim that the entity lacks
physics is refuted. Presence does not prove that the body/controller is active
or explain why input produces no movement.

### The HUD red cable is an ALC timeout, not a REP transport verdict

The icon the user sees is on the **left edge, vertically centred**: a network cable
with a red X and a warning triangle. Sequence described by the user: appears on
entering, goes **yellow** for a while, then stays **red**.

**`Game.log` does not record this icon at all.** `OnLocalNetworkConnectionWarning`,
`transportError`, `disconnected from REP` and `State(...) is timeout` say nothing
about it — three diagnoses in one session were wrong for exactly that reason. The
only instrument that sees it is a screenshot; `scripts/watch-indicator.py` classifies
that box as RED / YELLOW / absent.

**Measured: the icon was RED for a whole 14-minute window while REP transport was
healthy.** At the same UTC second the server logged 1243 `app-data`, 972
`outbound-app-data`, 739 `reply`, 59 `heartbeat`, 58 `keepalive` and 58
`input-response` events in the last 60 s, with the newest traffic event matching the
current clock to the second; the client logged `transportError` 0, `disconnected
from REP` 0, `OnDisconnection` 0, `is timeout` 0 and exactly one
`clientContext == nullptr` (the normal transient at the frontend→world transition).
The icon means the client's ALC input stamp is stale; it does not mean the REP
transport disconnected. Evidence:
`hud_cable_icon_is_not_the_log_20261010` in
[`client-functions.json`](research/atlas/client-functions.json).

Separate and still open: holding W produced no movement-family messages. The
older screenshot ratio is not valid proof of position; measure the live transform.

### Movement: the client never emits anything (measured 2026-10-10)

Holding W for 2 s in a stable in-world session produces **no movement message in
either direction**. Decoding every client->server record in that window gives
zero `StartMovementCommunicationMsg`, `AckMovementMsg`, `CommitMovementMsg`,
`MoveActorMsg` and `ReceivePlayerPositionClientMsg`. The channel-1 local-player
stream (119/120 B, actor `1a954abc…` at offset 8, raw payload with no typed
marker) is **byte-identical across 3038 records** taken while W was held: masking
the rolling 4-byte counter at offset 0, only two bytes ever differ (offset `0x31`
and `0x4e`). No position, no orientation, no velocity. The client's own
`teleport_player` command (T) does not move the player either.

This proves that the sampled input did not produce a movement-family message and
that the channel-1 stream did not carry a changing position. It does not prove
the entire client simulation state. The player's physics component types are
present; measure activation and the input consumer before deciding which server
message is missing.

### Movement blocker (re-measured; the earlier diagnosis is corrected)

The client broadcasts its local-player state on channel 1 (type `0x635`) and the
server answers only on channels 0 and 3. The capture contains **no movement
message in the server->client direction at all**, so the reply must be
constructed server-side.

One lead remains: `FUN_141763b70` ran exactly once at process startup, before
world entry, and `FUN_141582430` was not called during the sampled login/spawn
window (`local_body_gate_never_runs_20261003_2250`). The latest component dump
then found physics and rigid-body components on the live player entity. Therefore
the gate observation is not proof that the entity lacks a body; trace its role,
activation state, and relationship to the live transform before inferring cause.

**Correction to the earlier "the player has no physics component" conclusion —
and it was worse than a partial correction.** The GUID list in
`local_player_has_no_physics_20261004` is **shifted by one entry**, and
`physics_component_guids_corrected_20261005` fixed only four of them, so the
record still disagreed with the binary. The shift: the old list gave
`GameRigidBodyClientFacetConfig` = `{0BCAB3AC…}` (that is `GameRigidBodyConfig`),
`GameRigidBodyServerFacetConfig` = `{0E0EDECA…}` (that is
`GameRigidBodyClientFacetConfig`), `GameRigidBodyComponentBase` = `{0C1F07A3…}`
(that is `GameRigidBodyServerFacetConfig`), and `CharacterControllerConfig` =
`{824E1E63…}` (that is `RockNRoll::CharacterSupportInfo`). And
`{B1237004-14E1-4327-8774-D2C5796230E7}`, recorded as `CharacterPhysicsComponent`,
**does not exist in this build at all**. The verified registry is
`research/atlas/az-type-registry.json` (4814 names, 4818 entries, 750 in the type
table), regenerated and checked by `reverse/tools/scan-az-types.py`.

**The old "no physics component" conclusion is refuted (2026-10-10).** The live
player entity (`0x207084fca10`,
**126 components**) HAS `CharacterPhysicsComponent` and `GameRigidBodyComponent`;
the client's own lookup `FUN_1413fb700` finds both on it. The old conclusion came
from searching for ids that do not exist — `{B1237004-…}`, recorded as
`CharacterPhysicsComponent`, is `PlayerDynamics`. What remains true is only that
the player **prefab** ships no physics component. Full evidence:
`local_player_components_step0_20261010` in
[`client-functions.json`](research/atlas/client-functions.json); probe
`reverse/probes/client/frida-player-components.py`. This refutes component
absence as the explanation. It does not yet distinguish body activation, input
consumption, ALC setup, or movement dispatch. Method requirement: the player
entity is only observable **during the world load** (an idle in-world run saw only
223-478 lookups, all for entities below 20 components), so the probe must attach
before entering the world. The next question is activation and transform change,
not whether the component types are present.

**Trap for anyone re-deriving these:** a loose scan for `<name>\0…<bare-guid>`
pairs a name with unrelated neighbours. It maps `Transform` to
`{5D9958E9-…}` (the AZ math struct) when the entity-component `Transform` is
`{484AE67D-…}`. Use the brace-wrapped `{GUID}` form only.

**The bundle call chain is now verified, not guessed.** `FUN_14643e7b0` (the
handler that logs `skipping ReceiveStateBundle`) → `FUN_146455e90` →
`FUN_14175ccc0` → `FUN_146af20d0` → `FUN_146af2340`, every edge a real call. The
call site shows `FUN_146af20d0` filling a **record id** and a **vector of fragment
objects** (not raw payloads — `FUN_146af2340` creates one object per fragment),
and `FUN_141717fc0` then indexes a handler table at
`state + 0x608 + record_id*0x10`. So the record id is a **handler index**, which
is why record id 1 is the local-player metadata slot.

**Where physics actually comes from.** The server replicates entities and
components through an **area-of-interest trait** system (`Amazon::Hub::Aoi`, 185
traits), as *records* carrying *fragments* — the `0x08` bundle. `PhysicsTrait`
owns state type `{F05E34C6-AF1E-476D-9472-5FC118FC4503}` and registers
`RegisterRigidBodyMsg` and friends. The by-name component creator
(`FUN_141416740`) was measured **never to run** during world entry, and the
capture's 79 fragments all carry `type_index` 1, so the replay never delivers a
rigid body either.

### The replication architecture, mapped (2026-10-10)

There are **three** message systems, and conflating them is what made the
protocol look opaque:

1. **AOI traits** (82 traits, 2276 trait/message pairs —
   `research/atlas/aoi-trait-registry.json`): server-side authority for entity and
   component state. A trait replicates state as **records carrying fragments**,
   which is what the `0x08` bundle transports. The record id selects a handler at
   `state + 0x608 + record_id*0x10`.
2. **Client messages** (1783 RMIs): component-facet method calls named
   `<Component><Client|Server>Facet_<Method>`. This is the system behind the live
   warning `RMIDispatch: The facet target ID couldn't be found` — the server calls
   a facet method on a facet the client does not have.
3. **Javelin typed messages** (144 — `research/atlas/javelin-messages.json`):
   session, hub and movement control, carrying a wire type number.

**The spawn protocol is now readable.** The client asks with
`PlayerSpawnPointRequestTrait::RequestPlayerSpawnPointMsg`; the server answers
with `ReceivePlayerSpawnPointSuccessMsg`; the manager runs
`ProcessSpawnQueueMsg`; and the body is created through
`PrefabSpawnRequestTrait::RequestSpawnPrefabMsg`. **Physics is registered
separately**, by `PhysicsTrait::RegisterCharacterMsg` /
`RegisterCharacterWithRepulsorsMsg`. `PhysicsTrait` alone registers **76**
messages, including `RequestCharacterSetPositionMsg`,
`RequestCharacterPositionDeltaMsg` and `RequestIsCharacterReadyMsg`.

So "give the player a body" is not one message: it is a spawn-point handshake, a
spawn-queue process, a prefab spawn **and** a physics registration — and the
capture contains only the first part.

### The state bundle is a RECORD SEQUENCE — corrected and verified (2026-10-10)

The `0x08` body is `[marker][01][varint SEQ][6 invariant bytes][varint length]`
then a payload that is a **sequence of records**, each
`[u8 record_id][u8 fragment_count][fragments…]`.

This replaced the earlier "one record, one fragment" model, which was wrong in a
way that passed every check it was given: it consumed all 79 captured bodies
exactly, because it treated the whole payload as one opaque fragment payload.
**"Consumes exactly" is necessary but not sufficient** — an opaque-remainder model
always consumes exactly, so that check cannot distinguish one fragment from many.

The discriminating evidence is the client's own reads. A live Frida probe on
`FUN_146af20d0` (one record) and `FUN_146af2340` (one fragment) measured, per
record, the bytes consumed and the number of nested reader calls, and:

- the `fragment_count` byte **equals the nested-call count in all 90 distinct
  records** (`01 30`→48, `01 09`→9, `02 03`→3, `03 01`→1, `0d 06`→6, `1d 13`→19);
- byte-exact on the 78-byte bundle: payload 66 bytes = **two records of 33
  bytes** (`48 03 …`, `49 03 …`), with the client measuring `consumed=33,
  fragments=3` for each;
- `record_id` is **sequential** across a session (1…`0x2e`, then `0x48`, `0x49`,
  `0x4a`) — a handler index, matching `state + 0x608 + record_id*0x10`;
- `SEQ` spans **1..53**, exactly the high-water the client logged live.

So the spawn record's fragment count is **48**, not 1. All 78 bundles round-trip
exactly through the new parser.

**The fragment grammar is also verified.** A fragment is
`[varint KEY][varint TYPE_INDEX][type-specific payload]` — **exactly two header
varints, no length field**. A live probe logging every varint read with its offset
shows the first two varints at offsets 0 and 1 in **300 of 300 fragments**, with 48
distinct keys and 47 distinct types and a **1:1** key→type binding. The keys are
sparse (0…77), which is a component slot table with freed slots, and the spawn
record has exactly 48 fragments with exactly 48 distinct keys. The payload length
is **implied by the type** (the reader consumes it through vtable `+0x90`), which
explains the variable fragment sizes.

**The container is now fully understood down to the fragment.** What remains is
the **per-type payload encoding** — one codec per component type. That is the
remaining long tail, and it is also what physics needs, since a physics component
would arrive as one of these fragments.

## Decompilation campaign

**50** targets in the committed manifest
(`research/atlas/decomp-campaign.json`: launch 3, login 2, server-select 11,
character-select 0, world-entry 12, in-world 22). Growth through `campaign add` /
`expand` now persists to that manifest instead of only to the ignored per-build
state, so it survives the machine. The bulk corpus remains complete:
423,579 `.pdata` ranges accounted for, **423,542 `ok` / 37 `fail`** (20 timeouts,
10 mid-function fragments, 6 payload-cap, 1 address-space), and it does **not**
cover the 13,943 leaf functions in `.text` that carry no unwind info.

## Next useful step

Follow the gated plan in [`docs/ROADMAP.md`](docs/ROADMAP.md): reproduce the red
ALC state and measure `+0xAA0`/`+0xAA8` plus the 20-minute exit on a fresh client;
then read the player's transform/body-controller state while pressing and
releasing W. Trace the channel-1 `0x635` consumer and the missing facet target for
reliable 4216. Change one evidence-backed variable per fresh process. Close only
when the actual HUD clears, the client stays in-world beyond 20 minutes and then
2 hours, and the transform changes with W and stops on release. Transport logs
and screenshots alone do not pass those gates.

## Project structure

The game profile/runtime, PAK index, tools, and old logs live in ignored
project-local paths (`private-client/`, `.azoth/`, `reverse/builds/`).
