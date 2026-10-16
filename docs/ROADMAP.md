# Roadmap

[`STATUS.md`](../STATUS.md) owns the current blocker and next experiment.
[`ARCHITECTURE.md`](ARCHITECTURE.md) owns repository boundaries, the Rust
direction, content rules, decompilation standards, and capacity gates. This file
orders the work without repeating those references.

## Work order

### 1. Make daily work predictable — in progress

- Use `.\az.ps1 setup` on a clean Windows checkout to install checksum-verified
  project-local Python and tools. Then use `.\az.ps1 dev`, `.\az.ps1 game`,
  `.\az.ps1 status`, and `.\az.ps1 stop` for lifecycle management.
- Finish auditing the remaining operator scripts by caller and purpose; keep
  focused one-off experiments out of normal startup.
- Keep generated tools, client profile, logs, and analysis output under ignored
  project-local directories. Never change the Steam install.
- On this existing checkout, run `python az.py migrate` after the active game
  and decompiler processes close; preserve old analysis output as an archive and
  start new work in the executable-hash workspace.
- After each experiment finds a working behavior, record why it worked, check
  side effects, simplify the implementation, and remove failed variants.

### 2. Both in-world acceptance gates are MET; duration is the open one

Movement, the HUD cable and the response contract were resolved on 2026-10-13/14. What remains
for this section is **duration**, and it is one specific client-side question.

- **Movement gate: MET.** All four keys move the player in the correct directions and it stops on
  release, measured with the client's own accessor (`nw_getPlayerPosition`'s handler calls
  `FUN_140fddfa0`): W 22.998 u, S 18.975 u, A 4.515 u, D 9.359 u over 5 s each, with W/S 179.9 deg
  apart and W/A 91.2 deg apart, path == net in every phase, and 0.000 u with no input. A
  one-variable A/B attributes it to the local player's own AOI state: with the state stream OFF the
  position is frozen at `(9343.6416, 2786.7327, 87.538)` and W does nothing. The missing piece was
  **record id 1**, which the stream's old floor of `0xA0` never sent.
  `MOVEMENT_WORKS_state_stream_enables_player_simulation_20261013`,
  `WASD_verified_all_four_directions_20261013`.
- **Connection gate: MET.** The same A/B shows the HUD icon **absent** with the stream on and
  **RED** with it off, and the ALC stamp it ages goes from frozen (growing to 262 s) to refreshing
  225 times in 140 s with a 100 ms maximum age. The cable is a client-side age of one timestamp;
  the record-1 stream is what refreshes it. `RED_CABLE_FIXED_record1_state_stream_refreshes_the_alc_stamp_20261013`.
- **A third defect was found and fixed on the way:** the continuous Carrier ACK range was pinned to
  the session's first sequence, so it passed half the 16-bit space at ~26 minutes and the client
  began retransmitting every reliable record (212x). Fixed with a sliding window; a session then ran
  **1 h 03 min** with zero connection warnings against 682 in the pre-fix arm.
  `ack_range_pinned_to_session_start_breaks_the_client_at_32768_20261014`.

**Open, and it is the only thing left in this section: what ARMS the client's teardown.** Sessions
now end by the client's own graceful `SM_DISCONNECT` rather than by a crash — measured at
**1 h 06 min 33 s** on 2026-10-14, with `exiting to main menu` 0 and `Cleanup()` 0, which is the
same signature the runbook records for a shorter REP-disconnect ending. The world stays rendered
because the client keeps its last frame after tearing REP down, so the visible symptom is a red
cable and no movement while the readout's `Time since last response` grows.
`session_ended_by_a_graceful_client_sm_disconnect_at_1h06m_20261014`,
`chunk_gap_decides_the_20minute_arm_20261011`, `exitA_gap20_run_outcome_20261011`.

**The 20-minute threshold is PASSED (measured 2026-10-15), and the fix is that the teardown
delegate has TWO sites.** A session spawned at `22:33:10.804` fired the delegate at `22:53:11.188`
— exactly **20 min 0.384 s** — with `CGame::ActorContainerDisconnect` 1 and `Disconnected from
REP` 1 while `exiting to main menu` and `Cleanup()` stayed **0**. `patch-exit-to-menu.py` was
skipping the exit virtual at `0x14100425F` correctly, but the `call CGame::ActorContainerDisconnect`
at `0x141004230` runs **before** it and tears REP down by itself. Both sites are now NOPed, and a
run spawned at `23:13:25.170` then stayed clean (0 `ActorContainerDisconnect`, 0 `Disconnected
from REP`, 0 `exiting to main menu`, 0 `Cleanup()`, 0 `transportError`, 0
`OnLocalNetworkConnectionWarning`) for **24 min 8 s**, the world still rendering, **no cable icon**,
and **W/S still moving the player at 23 minutes**; a second probe-free run reproduced it at **24.5
minutes**. Both ended because of OUR OWN instrumentation (a probe's exit kills the client; a detach
faults it), not because of the client. **A third run, fully probe-free, then passed 30 minutes**
(spawn `01:03:30`; at **31.9 minutes** 0 of every marker, still running). So the 20- and 30-minute
thresholds are crossed; the **2-hour soak is the remaining gate**, and every soak must be probe-free. The arm itself was not targeted because the delegate's function
pointer has no static reference anywhere in the image (0 `E8` callers, 0 `lea` xrefs, 0 qword
literals), so the enqueue site builds it dynamically. This is a private-runtime affordance, not a
protocol fix. `20min_teardown_delegate_has_two_sites_20261015`.

- **Acceptance for this section:** in-world past 30 minutes, then a 2-hour soak, with the real HUD
  warning clear and no transport error. Transport uptime alone does not close it. **The 20- and 30-minute thresholds are crossed and two hours of liveness is reached
  (2026-10-16: 124+ minutes probe-free, 0 teardown/disconnect/transport markers, ACK stream
  healthy)**, but the acceptance is NOT met: from ~94 minutes the client's InGame state times
  out every 30 s and the HUD warning goes RED, while every server-side emitter is unchanged.
  The one measured change is the client's channel-1 ALC input record stepping from 313 to 122
  bytes. So the remaining gate is the ALC input/response contract, not duration. See
  `two_hour_soak_survives_but_the_state_timeout_arms_at_94_minutes_20261016` and
  `research/sessions/session-20261016T0103Z-two-hour-soak/`; soak runs must be probe-free.
- **Soak runs must be probe-free.** A measurement probe caused the last client crash
  (`frida-agent.dll` execute-after-unload, delayed by minutes); `frida-player-position.py` now ends
  through `_paths.safe_shutdown()`, but most probes still call `session.detach()` directly.
  `frida_unload_crash_mechanism_and_the_fix_20261012`,
  `session_still_crashes_and_the_cable_classifier_has_a_red_background_false_positive_20261013`.
- Reproduce each baseline on a fresh `NewWorld.exe`; change one variable per attempt and record
  build hash, config, logs/probe counters, HUD result, transform delta, duration and negative
  results in the atlas before closing the run.
- Implement only the protocol behavior those measurements establish in the Python prototype;
  preserve fixtures and observed outcomes for the later Rust port. Do not estimate a finish date
  until the ALC and movement call paths are identified.

### 3. Complete the client-visible server contract

- **The outbound half is measured and request-correlated (2026-10-14).** Captured typed
  responses are sent only when the client sent the request they answer; see
  [INBOUND-REQUESTS.md](../research/docs/INBOUND-REQUESTS.md) and `AZOTH_REPLAY_REQUEST_GATING`.
  Verify a change to the map with `python scripts/request-response-map.py --check`.
- **The inbound dispatcher exists (2026-10-14).** `rep.py::_dispatch_inbound` decodes the client's
  typed requests and acts on them. The request shape is measured: after the type marker the first 16
  bytes are the target facet's local id. Two things follow from that: the server **learns the time
  facet's address from the client's own `0x1098`** (all 151 live `input-response` events report
  `target_source: client-request`), and it **answers the contracts request once per ask** with the
  captured `0x08E6`, which the replay could only send once for the whole session. See
  [INBOUND-REQUESTS.md](../research/docs/INBOUND-REQUESTS.md) and
  `inbound_dispatcher_answers_requests_and_learns_facet_addresses_20261014`.
- **Next: express authority as REPLICATED STATE, not as a typed reply (measured 2026-10-14).** The
  five state-carrying requests were investigated for an authoritative effect and **cannot have one**:
  the protocol has no client-facet reply for them (`PlayerSettingsComponent` has exactly one message,
  the ServerFacet request; `ObjectivesComponent`'s client facets are warnings and a debug one;
  `GlobalStorage`'s are storage-search results behind a request the client never sends), and the one
  family that does have a reply — Time — is **ignored by the client**: with the `0x1097` payload forced
  to `0`, `1` and `3` on the wire, the client's own `lc_getTime` still showed `day` and its clock ran
  at the same 12.2× in every condition, including with no time sync sent at all. The one thing ever
  measured to make the client APPLY server data is the record-1 `0x08` state stream. See
  [INBOUND-REQUESTS.md](../research/docs/INBOUND-REQUESTS.md) §3 and
  `state_carrying_requests_have_no_reply_and_the_client_ignores_the_time_sync_20261014`.
- **The server can now COMPOSE a state bundle, and the client applies it (2026-10-14).** The
  local-player record's fragment layout was derived from the client, recomposition is asserted
  byte-exact on every send, and a field override written by the server was accepted with 0 unmarshal
  errors while the world rendered normally. `AZOTH_STATE_AUTHORITATIVE` (default 0) and
  `AZOTH_STATE_OVERRIDE`. See `state_bundle_can_be_composed_from_fragments_and_the_client_accepts_it_20261014`.
- **Next: make the composed bundle carry a field whose effect is MEASURABLE.** **DONE 2026-10-14:**
  the server now owns the player's **position**. The position was not in the 7154-byte record-1
  bundles the stream sends at all - it is in the **46393-byte spawn record** (48 fragments, replay seq
  `0x2a..0x6c`), which sits below the stream's `MIN_SEQ` floor of `0x94`, so the replay sent it once
  and the stream never did. That is why the position stayed anchored at the capture's value for the
  whole history of the project. Located **by value** (x/y byte-exact at payload offsets 38332/38336 as
  f32be; z is not in the payload in any encoding, so the wire carries a 2D position and the client
  derives the height). With `AZOTH_STATE_POSITION=9353.7227,2766.0681` the client's own accessor
  reported **exactly that**, **0.0000 u** from what we wrote and 22.99 u from the capture's.
  `server_owns_the_player_position_measured_20261014`.
- **Next: stream the position, not just the spawn one — ATTEMPTED AND REFUTED (2026-10-15).** The
  position-bearing spawn record was streamed with a fresh replication counter (75+ sends, 99
  overrides, four positions rotated mid-session) and the client's accessor never moved: **577 samples,
  0 unmarshal errors, 0 transport errors, position frozen.** The spawn record is consumed once at
  spawn, so "send the record again" is not the mechanism. `AZOTH_STATE_POSITION_STREAM` (default 0)
  keeps the capability because it is proven at the wire level and is needed to test any future
  position field. `AZOTH_STATE_POSITION` now also accepts `file:<path>`, re-read on every send, which
  is what makes a mid-session change possible at all. See
  `streaming_the_spawn_record_does_not_move_the_player_20261015`.
- **All THREE record-1 shapes are CLOSED for imposing a position (2026-10-16, the last one with
  the confound removed).** Testing at rest cannot tell "applied" from "ignored", so the
  DELTA-shaped 9-fragment bundle — the most native carrier, what the client receives ~4/s — was
  tested with the player **23 u then 55 u DESYNCED**: 266 sends, every one accepted (0 unmarshal
  errors), and the client **did not move**. Together with the full spawn record and the minimal
  1-fragment bundle (both accepted and ignored), every shape the client actually receives is now
  measured dead for imposition, which is what ALC predicts: the client is authoritative over its
  own position and the server validates. Do not spend more time trying to push a position.
  `the_delta_shaped_position_bundle_is_accepted_and_ignored_with_desync_present_20261016`.
- **The earlier re-send family note, kept for the record:** The spawn record's 48 fragment boundaries were
  measured from the client (`frida-record-boundaries`, attached at character select, `tiles: True`),
  locating the position's fragment exactly: payload `38310..38397`, an 87-byte fragment (`key=16`,
  `type_index=11`) with the position at payload offset 20. The server then composed a **minimal
  record-1 bundle carrying only that fragment** and streamed it at 4/s: 540 sends, three positions
  rotated mid-session, the outbound datagrams decoded to prove the wire carried `(9300.0, 2750.0)`,
  and the client's accessor read **358 samples without moving**. The earlier negative re-sent all 48
  fragments; this one sends one, and the client ignores that too — so the reason is not the fragment
  count, bundle size, record id, replication counter or value encoding. **The client consumes the
  position once, at spawn.** Do not try this family again. See
  `client_ignores_a_resend_of_the_position_bundle_full_or_minimal_20261015` and
  `spawn_record_fragment_boundaries_measured_20261015`.
- **The 4216 route is CLOSED (2026-10-16, static).** `IPositionReceiver`'s position method is a
  **`ret 0` stub** in this build: the delivery `FUN_143f97bf0` calls `target->vtable[0x40]`, the
  QueryInterface `0x143fadd00` returns `this`, and `0x1482eb160 + 0x40` (the implementation vtable the
  installer `0x143f983d0` stamps) is `0x140294860` = `ret 0`, with `+0x40..+0x58` all that same stub.
  So even a perfect address and a bound object would do nothing, which explains every failed 4216
  attempt with one cause. Do not spend more time on this message. See
  `ipositionreceiver_position_method_is_a_ret0_stub_20261016`.
- **What the server CAN do: read the position.** The client streams its own on channel 1 (wire `0x635`)
  and `javelin/alc.py` parses it (residual 0.54 u standing / 0.81 u walking against the client's own
  accessor). So observation works and imposition does not, through the paths tried so far. The
  remaining question is which channel the real server used to correct a client that simulates locally -
  and the strongest untouched candidate is the AOI state-record path with a record OTHER than record 1
  (the stream already carries record ids 70/72/75, and only record 1 was ever tested).
- **Next: find what the client treats as authoritative position INPUT.** The player's x,y is persistent
  replicated state on the entity (after W moved the player to `(9353.7227, 2766.062)` the accessor
  reported exactly that), and the streamed 7154-byte record-1 bundles do not contain the position pair
  at all, so the stream enables the client's own simulation rather than carrying the position. The
  consumer to locate is behind `InstallRegistrationHook<ReceivePlayerPositionClientMsg,
  IPositionReceiver>` / `RegisterInterfaceDecoupler<IPositionReceiver>`: the interface descriptor is
  the vtable at `0x1482ea4e8` (slot `+0x20` = `ret 0` default, slot `+0x28` = installer `0x143f983d0`
  which stamps implementation vtable `0x1482eb160`), and the open question is which class ever
  receives that stamp. Acceptance: the client's accessor reports a position the server changes
  MID-SESSION.
- **The server can now READ the position the client claims (2026-10-16).** The client's channel-1 ALC
  stream (wire `0x635`) carries its own world position as two big-endian float32 values, at a fixed
  offset from the 0.05f quantization anchor (which occurs exactly once in every body that has one).
  Measured against the client's own accessor, the residual is **0.54 u standing / 0.81 u walking**
  once the geometric reference offset is removed; the direction of movement matches to 0.3°. So the
  observation half of server-side movement validation now exists — see
  `services/world/src/azoth_world/javelin/alc.py`, `AZOTH_ALC_POSITION`, and
  `server_reads_the_clients_own_position_from_channel1_20261016`.
- **Server-authoritative movement: CLOSED as read / validate / detect desync (2026-10-16).**
  `services/world/src/azoth_world/movement.py` provides both halves: `MovementValidator` (speed
  over a 0.5 s window + a dt-independent teleport check) and `DesyncTracker` (the client's claim
  against the position the server believes). Wired into `rep.py` with `AZOTH_MOVEMENT_VALIDATION`
  (default on) and measured bounds. Validated live: 0 speed/teleport flags over 2404 samples
  (`max_speed_seen 9.226 u/s`), and desync 0 reports at rest (`max_deviation_u` 4.031, the measured
  instrument offset), 0 over a 19 u walk, then **143 reports / max 28.057 u** past the 25 u
  threshold. **CORRECTION is not available in this build and that is measured, not assumed**: all
  three shapes of the player's own record are accepted-and-ignored (the delta-shaped one tested
  with the player 23 u then 55 u desynced) and `IPositionReceiver`'s method is a `ret 0` stub. So
  the client is authoritative over its own position and the server reads, validates and escalates
  - which is what ALC means. `server_authoritative_movement_read_validate_detect_desync_20261016`.
- **The earlier validation-only note, kept for the record:**
  `services/world/src/azoth_world/movement.py` (`MovementValidator`) turns that stream into
  speed/teleport verdicts, wired into `rep.py` with `AZOTH_MOVEMENT_VALIDATION` (default on),
  `AZOTH_MOVEMENT_STATS_LOG_S` (30), `AZOTH_MOVEMENT_MAX_SPEED` (30 u/s),
  `AZOTH_MOVEMENT_MAX_TELEPORT` (50 u) and `AZOTH_MOVEMENT_SETTLE_S` (10 s). Bounds are loose ON
  PURPOSE and verdicts are logged, not acted on: measure real movement before choosing a policy.
  Validated live with **3208 samples and 0 false positives** (`max_speed_seen 14.64 u/s`, matching an
  independent 14.474 measurement), with the one-time ~18 u spawn transition excluded because it reads
  as 239-366 u/s and is not movement. `round_none_in_the_alc_hot_path_dropped_every_session_20261016`.
- **The model this settled, and it is the important part (2026-10-16).** A full scan of the capture:
  **71 of 78** state bundles carry position pairs, but the record-1 (local player) bundles split
  cleanly — the SPAWN copies carry **7** position pairs and **every delta copy carries none**. So the
  local player's position is replicated state sent **only when it changes**, and the capture has no
  example of a server correction (the author stood still). Combined with the three measured dead ends
  (the 4216 method is a `ret 0` stub; the full spawn record re-sent with a changed position is
  accepted and ignored; a minimal 1-fragment bundle likewise), ALC has the **client authoritative
  over its own position** and the server validating. So "server-authoritative movement" here means
  the server READS, VALIDATES and corrects — not that it drives the client's position.
  `the_local_players_position_is_replicated_state_sent_only_when_it_changes_20261016`.
- **The 2-hour soak's remaining gate is the client's own degradation at ~94 minutes.** At `02:36:56`
  the client's channel-1 record stepped once, discretely, 257-259 B -> 68 B; 29 s later (exactly the
  watchdog's 30 s budget) the first `State(InGame) is timeout` appeared and then repeated every 30 s;
  the HUD went RED at ~03:07 and the client stopped responding at `03:18:34`. Every server-side
  emitter is constant across the onset and the ACK stream is healthy, and the client's PID never
  changed. In the decoded terms above, the step is the client's input batching going from four
  entries to one — an inference, since the entry grammar is not decoded. Next: decode that grammar,
  or find which `javelin.alc-*` cvar governs the batch size, and test whether answering the
  channel-1 stream keeps the larger form. `channel1_record_step_at_94_minutes_precedes_the_state_timeout_20261016`.
- The requests remain decoded, counted and shape-logged (`inbound-request-shape`) and stay in the
  coverage line's `no_replay_response` every session, so the remaining work is visible rather than
  guessed. Do not emit a plausible reply for a setter without evidence.
- Let new client requests and failed state transitions set the next protocol
  work item; record exact fields and evidence in the atlas.
- Keep the gateway and world process boundaries until measured requirements
  call for a different deployment shape.

### 4. Port understood behavior to Rust — the trigger is authority, not calendar

- Start the workspace when the first behavior is ready to port, not as empty
  scaffolding.
- **Assessed 2026-10-14: not yet, and the reason is specific.** The server is still mostly a faithful
  **replayer**: everything in the state stream except record 1 is forwarded captured bytes, and the
  server does not yet decide the player's position over time. Rust exists here to reach 2,500 then
  10,000 concurrent players, which is a **simulation** target that cannot be expressed while there is
  no authoritative simulation to port. The trigger for that, though, has started to move: see below.
- **STARTED 2026-10-15, with the one piece this section itself named as port-ready:**
  `server/` is now a cargo workspace whose `crates/protocol` ports the wire codecs
  (`varint`, the type-0x08 state bundle, the fragment grammar) from the Python reference, with
  **zero dependencies** and **12 passing tests** (8 unit + 4 parity). `tests/parity.rs` reads a
  fixture generated by `scripts/gen-protocol-fixture.py` FROM the Python codecs — every captured
  varint case, byte-exact re-encode of 49 captured bundles, the client-derived record-1 fragment
  boundaries and (key, type) pairs, fragment recomposition, and the position anchor at spawn-payload
  offset 38332 — which is the "compare Rust and Python at the wire boundary using the same fixtures"
  rule in practice. `scripts/gen-protocol-fixture.py --check` fails if the fixture stops matching
  Python, so the two cannot drift. `rust_protocol_crate_with_python_parity_20261015`.
- **What IS ready to port** (measured, fixtured, and stable): the wire codecs (`varint`, `vlq32`,
  `bundle`, `frame`, `lz4`) and the DTLS/Carrier/V3 connection path. They have round-trip tests
  against the captured corpus.
- **What is NOT ready:** the replay pump and the response-scheduling policy, which are scaffolding
  that will be replaced once the server owns the world state; and anything in
  `services/world/src/azoth_world/rep.py` that exists to make a capture behave.
- **Trigger:** the first behavior the server decides rather than replays. **That trigger is now
  MET (2026-10-14):** the server composes the local player's own state bundle from fragments instead
  of forwarding it, AND it decides the player's position — the client's own accessor reports a
  position the server wrote, 0.0000 u from what it sent. What is still a replay is everything else in
  the stream, and the position is applied at spawn rather than over time. The next Rust question is
  therefore about scale, not about readiness: port the protocol crate once a second authoritative
  behavior exists, so there is a shape to port rather than one.
  A defensible narrower start, if Rust is wanted sooner: `server/crates/protocol` with the codecs
  and a byte-for-byte parity test against the Python encoders over the captured corpus. That is the
  only genuinely port-ready piece and it does not displace the dispatcher work.
- Compare Rust and Python at the wire boundary using the same fixtures and
  observed client results. Remove Python only after each behavior has parity.
- Keep developer tools and diagnostics outside production server binaries.

### 5. Add content and establish capacity

- Add supported client content as validated data with stable IDs. Implement
  new authoritative behavior in the world runtime; identify client changes
  separately.
- Measure 2,500 active players first, then work toward 10,000 per server using
  the workload and measurements defined in `ARCHITECTURE.md`.
- Do not claim a capacity target until a sustained representative run records
  hardware, workload, latency, tick deadlines, bandwidth, CPU, memory, and
  reconnect results.

## Explicitly deferred

- A full 423k-function decompilation run is explicit via
  `python az.py re corpus`; setup never starts it in the background. The old
  per-user corpus is preserved locally as an archive, not input to the new workspace.
- Do not add a database, queue, fleet scheduler, content DSL, service split, or
  generic plugin system until an implemented feature or measured bottleneck
  requires it.
- Keep detailed protocol evidence in focused `research/docs/` references and
  `research/atlas/`; do not create a second task tracker for the same work.
