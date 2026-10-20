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

- **Acceptance for this section:** in-world past 30 minutes, then a 2-hour soak, with the real HUD
  warning clear and no transport error. Transport uptime alone does not close it.
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
- **Next: stream the position, not just the spawn one.** The position is applied **at spawn** from a
  record the replay sends once, so today the server decides the starting point and not the position
  over time. The same override applies to any body carrying the pair, so the work is to get a
  position-bearing bundle into the continuing stream (or compose one) rather than to find the field
  again. Acceptance: the client's accessor reports a position the server changes MID-SESSION.
- **The client's own claim is now readable, and the desync policy is written (2026-10-18).**
  `javelin/alc.py` reads the player's position out of the channel-1 input stream the client already
  sends ~20x/s: type `0x635` (1589), two `f32` big-endian located by the `0.05` marker, verified over
  **213,202** captured records (197,810 carry a position, 0 ambiguous, and the block *moves* between
  body offsets so the marker is required). `movement.py` adds `MovementValidator` (speed window +
  teleport), `DesyncTracker` (claim versus the **server's own** position, floor derived from
  `max_speed * rtt`, sustained over N samples) and `LoadGate`. **Wired into `rep.py` as a read-only
  observer** (`AZOTH_MOVEMENT_OBSERVE`, default on) logging `movement-ready` / `movement-desync` /
  `movement-reject` on transitions only — but **not yet exercised by a live run**, which is the
  immediate next step and what turns step 3 from a module into a measurement.
- **The 2-4 u offset is an instrument property that MUST be subtracted — measured live 2026-10-18.**
  Against the client's own accessor with the player still, the wire claim differs by 2.0-4.0 u, constant
  within a session (residual 0.0000 u in two of six) and different across sessions. The first
  `DesyncTracker` compared raw claim against server truth and argued no offset was needed; a live run
  refuted it — a still, in-sync player showed **exactly 4.0311 u in all 2,562 samples** and was reported
  as desynced. The offset is now calibrated per session **without a probe** (at spawn the client is where
  the server put it), rejected when the samples are not tightly clustered, and the tracker **fails open
  while uncalibrated**. Live: calibrated `(-2.2002, +3.3777)` / residual 0.0000 -> no desync; then `W`
  held 3 s -> `movement-desync` 3.342 u, which is real. **Detection works; correction does not.**
- **The position fragment is located, and sending it alone does NOT move the player (2026-10-18).**
  The spawn payload's 48 fragment boundaries were read from the client (`frida-fragment-grammar
  --min-fragments 20`, 25 byte-identical captures). The position is **fragment #35**, payload
  `38310..38397`, `key=16 type=11`; all 24 captured copies carry a byte-identical fragment. That
  composes a **101-byte** record-1 bundle, 451x smaller than the 46 KB spawn record — and it is
  accepted with 0 errors and leaves the character visible, but the error **grew to 16.5 u and
  stayed there**. A single-fragment record is not a repositioning message. The position is
  **locatable but not addressable** as a standalone message. `AZOTH_MOVEMENT_CORRECT` defaults to 0.
- **STATIC: the record dispatcher explains the negative, and the next experiment is built
  (2026-10-18).** `FUN_141717fc0` applies a record only when `byte[msg+8] == 0` **or** the record's
  handler slot (`state + 0x608 + record_id*0x10`) was empty — otherwise it is silently skipped. And
  it branches on a **virtual call derived from the record's FIRST fragment**, so a record is not an
  unordered bag of fragments: the first one selects the path. That is why a 1-fragment record whose
  only fragment is the position is ignored. `rep.player_body_with_position_fragment` now composes
  the **7154-byte record-1 bundle the client demonstrably applies** plus the position fragment —
  **7255 bytes, `record_id=1`, `fragment_count=10`**.
- **RUN, AND REFUTED (2026-10-18).** That hybrid was sent twice, reliable (`0x21`) and unreliable
  (`0x20`, the form the capture uses and the only one that advances `port[0x78]`). **Both were
  accepted with zero client errors, left the character visible, and changed nothing**: the error
  grew past the correction to 11.861 u. So **neither composition nor the flag byte is the
  obstacle**. Four shapes are now refuted (full spawn looped → character invisible; fragment alone;
  hybrid reliable; hybrid unreliable). Correction by sending state bundles is closed for this
  build. What is still open is *why* the client ignores a record it parses.
- **ANSWERED (2026-10-18, static): the update path is per-fragment and gated.** `FUN_141717fc0` has
  two structurally different apply paths. **Creation** (slot `state + 0x608 + record_id*0x10` empty)
  applies the whole record in one call, no filter — which is why the spawn record works. **Update**
  (slot exists — every correction) loops the fragments and calls a **virtual predicate at
  `fragment->vtable + 0x60`**, adding to the component map only the fragments whose predicate
  returns **0**; the rest are silently skipped. So a correction must satisfy a filter **the server
  does not control**, and the filter is **not about the bytes we send** — which is exactly why four
  payload shapes failed identically. Next targeted question: which component type owns that vtable
  and what the predicate tests. Do not attempt correction again by guessing payloads.
- **The vtable identification was ATTEMPTED AND FAILED (2026-10-18).** Pattern-matching `.rdata` for
  the `+0x60` slot value landed on a **serializer** vtable (`+0x60` is `read(n)`, returning a cursor
  position rather than a bool, so it cannot be the value the dispatcher tests). Recorded as
  `fragment_object_vtable_identification_FAILED_20261018`. The correct method is to take the vtable
  at **runtime** from the object `FUN_146af2340` constructs, not to match slot values in the file.
  The two-apply-paths finding does not depend on it.
- **ANSWERED AT RUNTIME (2026-10-18), and it corrects the static reading.** A probe read the vtable
  the dispatcher actually calls: the `+0x60` slot is the **same for every fragment** and is
  `xor al, al; ret` — it returns 0 unconditionally, so **there is no per-fragment filter** and every
  fragment is processed. The real mechanism is that the component maps (`FUN_1415e5140`,
  `FUN_1415e68b0`) are **FIRST-WRITE-WINS**: an already-present key is not replaced and the new
  fragment is discarded. The spawn works because the keys are absent; every correction re-sends
  key 16, which is already present, so it is dropped — which is exactly the measured “accepted,
  zero errors, no effect”. **Re-sending a key cannot work by construction.** The next experiment is
  a REMOVE-then-INSERT (the AOI registry already has `replica_portrayal_remove`) or a delta/update
  message, not another payload shape.
- **CLOSED (2026-10-18): the position is SPAWN-ONLY in replicated state, by design.** `record_id 1`
  has two variants. The **spawn** variant (48 fragments, 46 393 B, 24 bundles) **does** carry the
  x/y pair. The **ongoing player-state** variant (9 fragments, 7 154 B, the five bundles the 4 Hz
  stream re-sends) carries `key=16 type=11` with the **same vtable** but a **49-byte payload and no
  position at all**. So no streaming and no payload composition can move the player through
  `record-1` — which is why four shapes failed identically and why the spawn override worked with
  0.0000 u. The ongoing position is **client-authoritative (predicted)** and server correction must
  travel on `ReceivePlayerPositionClientMsg` (4216) → `IPositionReceiver`, the channel this build
  **never instantiates**. **The acceptance criterion for this item (“the client's accessor reports a
  position the server changes MID-SESSION”) is therefore unreachable via replicated state** and
  should be re-scoped to the correction channel, or dropped, rather than retried with more payloads.
- **THE CORRECTION CHANNEL IS ALSO DEAD (2026-10-18, static): `IPositionReceiver`'s apply method is a
  stub.** The delivery `FUN_143f97bf0` applies through `vtable[+0x40]`, and on the interface vtable
  `0x1482eb160` that slot is `0x140294860` = **`ret 0`** (as are `+0x48/+0x50/+0x58`), while
  neighbouring slots are real. A full `.rdata` search for the QI pointer finds **exactly two
  occurrences, both inside that same vtable**, so **no static concrete class implements it**; and
  the measured session found `installer=0` / `register=0` for 18 minutes, so none is built at
  runtime either. This also re-explains the old “delivery succeeded 260/260” result: it was measuring
  the stub. **Server authority over the local player's ongoing position is not reachable through any
  channel measured in this project.** Do not spend more sessions on it; if it is ever wanted, the
  only path is a client-side hook, which is out of scope for a server-faithful implementation.
- **THE DESIGN, RECOVERED FROM THE CLIENT'S CVARS (2026-10-18) — and it is not a position push.**
  Every correction cvar is CLIENT-side (`javelin.alc-correct-position-desync-during-attack-slow-down`,
  `-lateral-desyncs-…`); every SERVER-side one is validation or input control
  (`javelin-server.alc-speed-hack-fix-v2-enabled` / `-wipe-inputs` / `-max-buffered-inputs`,
  `player-teleport-2d-distance-metrics-threshold`, `alc-validate-sector-bounds`,
  `num-inputs-to-wait-for`, `ALC-max-input-to-combine`, `alc-request-input-throttle-server-override-delay-ms`).
  **The client is authoritative over its own locomotion; the server validates and reacts.** A
  correction is the server refusing/throttling/wiping inputs, after which the client reconciles —
  there is no server→client position-push message to find. `SetInputsThrottled` (0x3e6) is
  client→server and is not that channel.
- **THE SERVER NOW HOLDS ITS OWN POSITION (2026-10-18).** `movement.MovementSimulator` seeds at
  spawn (the one moment the server genuinely decides) and folds forward the client's validated
  claims, recording `Authority` per sample and holding its own value when a claim is implausible.
  The step is measured against **the server's** position, not the client's previous claim, because
  the validator resets its reference on a rejected teleport — otherwise an insisting client would
  win after one refusal. `AZOTH_STATE_POSITION=sim` publishes that position into the state the
  server sends. **This is the first behaviour that makes the world server a server for the player's
  position rather than a replayer** — the Rust trigger from item 4 is now met on this axis.
- **THE INPUT STREAM IS DECODED (2026-10-18).** The channel-1 body carries a movement block right
  after the `0.05` marker: `a`, `b`, **x**, **y** as big-endian float32 (payload 119+4/+8/+12/+16).
  **x and y match the position claim 34 of 34 distinct positions and 201 of 201 samples** — the
  client reports its position twice in the same body. `a` and `b` vary with movement but their
  meaning is NOT established, so they are exposed raw rather than guessed at.
- **THE SERVER PREDICTS NOW (2026-10-18).** `movement.PredictiveSimulator` estimates velocity from
  consecutive **server-held** positions, predicts the next, and records the prediction error while
  still adopting plausible claims. Measured: a 3 s walk at 5 u/s with noise gives **0.0654 u mean
  prediction error** and 0 disagreements; a 900 u teleport in one sample is **refused** and the
  server keeps its own position. So the server can now say *“that step does not follow from what you
  reported”* instead of only *“that step was too fast”* — with the client still authoritative over
  its locomotion, as the cvar names say the original does.
- **THE MOVEMENT BLOCK IS FULLY DECODED (2026-10-18): `(pitch, yaw, x, y)`.** Over **1008
  displacements**, `a` is the **camera yaw** — classifying each by `(heading − a)` gives 47.8% at
  +90° (strafe left), 24.4% at +180° (back), 11.8% at −90° (strafe right), 5.4% at 0° (forward); the
  “direction of travel” reading fits 5.4% and is **refuted**. `b` is the **camera pitch** — it
  changes only **770 times in 197 810 samples** (mean run 256, like the yaw's 729/271), spans
  −30.3°…+26.1°, and **691 of 808 angle changes are simultaneous with the yaw** while 79 are
  pitch-only. The pitch is recorded but **not used**: the wire carries a 2D position, so movement is
  planar and a pitch cannot contribute.
- **`YawAwareSimulator` (2026-10-18):** velocity is expressed in the **player's own frame** (forward
  along the yaw, lateral across it), so the server says *how* the player moves, not just how fast.
  Measured on **4001 real samples with both angles**: 29 violations, 8 prediction disagreements,
  **mean prediction error 0.0419 u**. That frame is the one a correction would have to be expressed
  in.
- **SOLVED (2026-10-18): THE CHANNEL CARRIES THE LIVE POSITION IN A BUFFER.** The body has two forms:
  **idle = 311 B with ONE position** (the spawn anchor, which does not follow the player) and
  **moving = 403–412 B with FIVE positions**, a sliding buffer of the last five movement samples,
  newest first at **20 Hz**. Every analysis in this project filtered for `len(payload) == 311`, which
  is why the anchor was all it ever saw. **Validated 600 of 600 entries** landing on the client's own
  20 Hz accessor trajectory within 0.5 u, across 120 messages, with a clean 0.051 s ladder.
  `alc.read_live_position` is wired into the server. **Step 1 of the authority loop is genuinely
  solved.**
- **Frame offset:** `wire = accessor + (−2.2002, +3.3777)`, constant to 0.000 u — a frame difference,
  not noise. The server stays in the wire frame; the constant exists only to compare against the
  accessor, and the simulator's seed was moved to the wire frame so its own state stays consistent.
- **RE-MEASURED WITH THE LIVE FEED, AND THE YAW WAS 90° OFF (2026-10-18).** `(movement heading − yaw)`
  is a constant **+90.0°** (77 of 79 displacements), so the yaw is measured from **+Y**: forward is
  `(−sin, cos)`. The obvious `(cos, sin)` reported a forward walk as a sideways one — `forward 0.00 /
  lateral +3.83` — and it was measured doing that. After the fix, on **133 real walking samples**:
  **forward 3.83 u/s, lateral 0.00, mean prediction error 0.1265 u, 0 violations, 0 disagreements.**
  These are the first movement numbers in this project taken against a real walk with a real feed;
  the earlier ones (4.0311 u constant, 0.0419 u prediction error) were measured against the anchor and
  meant nothing.
- **THE SERVER ENFORCES AUTHORITY (2026-10-18), verified live.** `CorrectionPolicy` escalates
  ACCEPT → HOLD → FREEZE → DISCONNECT, where FREEZE is the measured lever (stopping the player state
  stream freezes the client's simulation), and it recovers after clean samples. Live run: the server
  tracked a real **23.02 u** walk, **adopted 3317 / violations 0**, mean prediction error
  **0.0027 u**, 3 decisions all ACCEPT, client clean. **A legitimate walk produces zero corrections.**

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
  server does not yet decide the player's position. Rust exists here to reach 2,500 then 10,000
  concurrent players, which is a **simulation** target that cannot be expressed while there is no
  authoritative simulation to port. The trigger for that, though, has started to move: see below.
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

## Next steps, in order (state after 2026-10-20)

The server is authoritative over the player's own movement **and** owns its inventory. Each item names
its acceptance test so it closes on evidence.

### The 2026-10-19 re-scope was tried and its premise was wrong (2026-10-20)

The re-scope said "move an EXISTING captured actor instead of creating one". Two live arms, and the
premise did not survive: **neither character record is a body that renders.**

- **A real bug was fixed on the way, and it is the same class the structure experiment paid for.** The
  move was gated on `msg.seq == MOVE_ACTOR_SEQ`, so it only patched the STREAM copy of the record and
  never the bundle that CREATES the entity. Measured: record 29's pair is in `0x77` (below the stream
  floor `0x94`, sent once by the replay) **and** `0xa1` (the stream). Now applied by value to every
  body that carries the pair; `MOVE_ACTOR_SEQ` only resolves the anchor. Live: `actor-moved` on both
  seqs. `the_actor_move_was_gated_on_the_source_seq_and_missed_the_creation_bundle_20261020`.
- **Record 29 (`0xa1`), 5.8 u from the player:** accepted with 0 unmarshal / 0 validation / 0 root
  errors and **no body appears**. It never rendered, so it was never a candidate.
- **Saradnax (`0x97`, record 94):** its slice instance declares its actor and then `18b03301040001a0`
  where record 29 has a real f32 pair — **the slice declares no transform**, and the only plausible
  pair is 84.3 u away. `moving_a_captured_actor_needs_a_body_that_renders_and_neither_character_record_does_20261020`.
- **The census was run (2026-10-20) and it redirects the work again.** A new read-only probe
  (`reverse/probes/client/frida-actor-transform.py`, native `Memory.scan`, the player id as positive
  control) searched the client for every actor id the capture declares. **Only four of the twelve are
  present** (rid 29, 30, 60 and, in one scan, 87); rid 79 and 88-94 — Saradnax, Marrlord, Vinicent,
  Nuna — are **absent**. So the rendered bodies are *not* held under their declared actor id, which is
  the opposite of what this re-scope assumed. Also negative: no actor id has an adjacent
  world-position pair in either endianness, and the player's own position is not findable as an
  adjacent f32 (or f64) pair anywhere in 3 GB — the accessor derives it.
- **The entities were then enumerated, and the render still does not follow (2026-10-20).** Guessing
  the `this+0x110` hash-table layout **failed** (it walked into code memory); the anchor that works is
  the client's own lookup `FUN_1413fb700`, whose `args[0]` is an entity and whose component count is
  `(entity+0x18 - entity+0x10)/8`. Attached at **character select**, a 40-component floor leaves
  exactly **15** entities: two of 126 (the live local player) and **twelve of 61** — the twelve remote
  actors the capture declares, now addressable for the first time.
- **But writing their Transform does not move the body.** Only one of the twelve carries a world
  position in its Transform (two consecutive 12-byte little-endian `(x,y,z)` triples at `+0xE48`,
  **with height**); the client keeps a written value (read back unchanged 3×), and the render does not
  follow — four arms, **0.12–0.13x** motion, this repo's "nothing moved" threshold. The other eleven
  have no such triple at all, so there is no common layout.
- **The RENDER-side component was tried and it is not it either (2026-10-20).** Naming every component
  of the entities the walk finds settles what they are: **thirteen entities of exactly 61 components
  are the remote-player shape** — `CharacterComponent`, `PlayerAppearanceComponent`,
  `SkinnedMeshComponent`, `PlayerSaveData`, `PlayerPositionTrackingComponent`,
  `AsyncRenderTransformComponent` — and they lack **every** local-only component (`PlayerAOIComponent`,
  `HUDComponent`, `CameraLockComponent`, `InventoriesComponent`, `AttributeComponent`,
  `CombatStatusComponent`). Thirteen against the twelve actor-bearing records the capture declares:
  **the remote player entities are addressable objects now.**
  `the_thirteen_sixty_one_component_entities_are_the_remote_player_shape_20261020`.
- **But their position is in neither transform, and the local player is the control that proves it.**
  Three windows (0x400, 0x8000, and a current+previous-closeness filter) over `Transform` and
  `AsyncRenderTransformComponent`: the hits land at **wildly different offsets** per entity (2904 …
  31332), which means they are **neighbouring heap objects read past the end of the component**, not
  the entity's transform — a real component layout puts a field at the same offset in every instance.
  And the live local player, which certainly renders, has **no** in-band triple at all. So *"find the
  transform offset"* is the wrong question. `the_position_is_not_in_the_transform_or_the_render_transform_of_any_entity_20261020`.
- **SOLVED (2026-10-20): the holder IS the Transform, and the layout is stride 0x10.** The position is
  `Transform +0x14c (x)`, `+0x15c (y)`, `+0x16c (z)` — **not** a packed 12-byte triple, which is why
  every scan in this project missed it. Established by decompiling `FUN_140fddfa0` and its handler
  `0x141015b30`, then reading the holder's vtable slot 0 at runtime: the type is `484AE67D-…` =
  **Transform**. Reading those offsets on the twelve remote entities reproduces the capture's declared
  positions **0.5–2.3 u** apart for all twelve, and the local player's value exactly.
  `the_world_position_is_at_transform_plus_14c_15c_16c_with_stride_16_20261020`.
- **What that gives, and where it stops (2026-10-20).** The server **owns the spawn position of a
  captured actor**: with `AZOTH_MOVE_ACTOR_SEQ=0xa1` the client's entity for record 29 comes up at the
  server's `(9351.80, 2786.53)` instead of the capture's `(9345.46, 2781.26)`. But the **client
  re-imposes** that position — a direct write to the Transform lands and is **restored in ~2 s**, with
  the render unmoved (0.08x against a 0.11x do-nothing control) — and changing the position file
  mid-session does nothing (1 write, the `0x77` creation bundle, against 264 stream sends of `0xa1`).
  That is the local player's mid-session wall, now confirmed **from the client**.
  `the_client_reimposes_the_entity_position_and_ignores_a_direct_write_20261020`.
- **CLOSED 2026-10-20: the position works end to end, and nothing is drawn.** The camera yaw was read
  from the client's own channel-1 stream (**−154.04°**, stable over 1.9 M samples), a captured actor was
  placed **3 u in front of the player** before the session started so the creation bundle `0x77` carried
  it, and the client's entity for that record — 61 components, the remote-player shape — came up at
  **(9342.5566, 2787.938)** against the requested `(9342.754, 2787.413)`. **The screenshot from the
  player's own viewpoint shows no body.** Client clean: 0 unmarshal, 0 validation.
  `the_server_position_reaches_the_client_entity_and_no_body_is_drawn_20261020`.
- **Therefore items 1 and 2 are blocked by ONE thing, not two: remote-slice PLACEMENT.** The position
  path works; the render path does not, and it is the same 26 `Couldn't get Transform component on the
  slice` warnings every session on this build emits. Do not spend more sessions on the position, the
  record shape or the slot — none of them is the blocker.
- **CORRECTED 2026-10-20: the interface is NOT missing from this build.** The "this build does not
  implement `{83482F97-…}`" reading rested on a census of **0 of 31 objects**, but that census hooked
  **one** `QueryInterface` — the one reachable from the slice job's vtable — and every other class has
  its own. Statically: the TLS getter for that type id has **631 call sites**, and **274 distinct vtable
  slots** point at functions that query it. So the interface is implemented by **274 classes**; it is a
  common interface. What stays true is narrower: the **slice job's** QI compares against exactly two
  getters and returns null for ours. The question is therefore not *"does the interface exist"* but
  *"why is the gate asking an object that does not provide it, when 274 others do"* — and that is open.
  `the_transform_interface_is_implemented_by_274_vtables_so_the_census_was_measuring_one_qi_20261020`.

### DONE 2026-10-19 (kept for the record)

- **`AZOTH_STATE_POSITION=sim` is the default and was verified live**: a 23 u walk tracked with 0
  violations and 0 client errors.
- **The correction ladder fired live, twice.** `AZOTH_MOVEMENT_FORCE` (a deliberate provocation, off by
  default) moves the SERVER's position, which makes the client's next claim diverge. Measured
  HOLD(1) → FREEZE(5) → DISCONNECT(1000), and the decisive observation: **the channel-1 payload
  collapsed from ~405 B (moving) to 120 B and the player froze for 8 s of held W.** The freeze lever is
  proven end to end.
- **A world entity can be moved by the server.** Rewriting a captured entity's position and sending it
  made the player stand **on a house that had not been there** - collision included. The write path
  works; the first attempt simply picked a structure instead of a character.
- **Inventory: acceptance MET.** TAB (scan code `0x0F`) opens an inventory the server composed - 428
  entries, 3 ids rewritten, 0 errors. A real gating bug was fixed on the way: `RESPONSE_REQUESTS[0x16A0]`
  required `0x169D`, which the client never sends, so a legitimate push was being suppressed.

### 1. Finish the entity story: a NEW actor, not a moved one

**STATUS 2026-10-20: creation is refuted (four independent measurements, below) and the "move a body
that renders" re-scope failed its own premise too — see the section above. The only remaining lever is
the actor/entity census, not another payload.**

**CORRECTED 2026-10-19.** The premise below was wrong in one important way and is fixed here, because
it sent a session down the wrong path. It said entity records carry "component GUIDs, not actor ids".
**A record DOES declare its actor id**, in a slice instance: in record 29 at payload offset **662**, the
shape `<remoteplayer.dynamicslice GUID><00 00 00 02><16-byte actor id>`, and the **same shape carries
the local player's id at offset 29731** of the 48-fragment spawn record. Only **12 of the 36** captured
record ids declare one at all (the character/creature records, 16-21 fragments; props and structures do
not), which is now a reliable discriminator.

The mechanism is proven; what is missing is **creation**. `ClientAddEntryMsg` (wire `0xa4`, 20 bytes) is
`[00 01][a4][16-byte actor id]` - it registers an actor, and the capture sends it twice for the player
before the spawn. So creating an entity is: register an actor id, then send a record whose slice
instance points at that id.

- **Step 1, cheapest: REFUTED 2026-10-19, with the strongest possible test.** Take a captured entity
  record and replicate it under a new identity; acceptance is "two bodies render where one did". This
  was tried twice. First with record 29 (19 fragments): two real bugs were found and fixed, the record
  reached the dispatcher and the slot was created and stable, but no body appeared. Then with the
  **48-fragment SPAWN record** - the one that provably produces the visible local player - with all 48
  fragments byte-identical, the position rewritten to 3.5 u from the player and the actor id rewritten
  to a new one. The client accepted everything (**0** unmarshal, **0** validation, **0** root errors)
  and **no second body appeared**. So the difference between the player and a remote entity is **not**
  the record's content, fragment count, actor id, position, slot or replication counter - every one of
  those is now controlled for. **The "long tail" note below is refuted too**: replication gets the bytes
  accepted and is not enough to get a body.
- **Two bugs that must not be re-introduced:**
  1. **The record slot must be one the client's table reports NULL.** The capture-derived set was a
     **lower bound** (it only ever saw the FIRST record of a payload), so the "free" slot 3 was
     allocated; the message was an update and the first-write-wins component maps discarded it.
     Measured: **ids 1..94 occupied, 95..255 NULL.** `entities.MEASURED_USED_SLOTS` carries this and
     `AZOTH_NPC_DUPLICATE=auto` resolves to 95.
  2. **The replication counter must advance.** `duplicate_entity` re-encodes the payload but not the
     prologue, so the bundle kept the capture's counter (0x26=38) while the client's high-water was
     **1216** - the gate dropped every bundle and record 95 never reached the dispatcher. It now shares
     the state stream's monotone counter.
- **Also measured:** re-sending the full 19-fragment record once per second makes the client rebuild
  the object (the slot's pointer changed 1:1 with the dispatch count) while **a single send leaves it
  stable**. `AZOTH_NPC_MAX_SENDS` is that one-variable lever.
- **Next instrument, and it is NOT another payload shape:** the actor/entity table (`FUN_146801040`,
  manager at `this+0x110`) counted before and after, plus a hook on the creation apply `FUN_14178db00`.
- **Step 2:** move the second one server-side and confirm the client follows it. That is a synced NPC.
- **The long tail, re-stated:** per-component fragment payload codecs are still undecoded, and mapping a
  fragment `type_index` to a component name through `typeindex.json` does **not** work (1 of 48 named),
  so the codecs have to come from the client's readers. But **composing is no longer the blocker**:
  replication was tested with the best possible record and produced no body, so decoding every codec
  would not help until the remote-slice placement works.
- **THE REAL BLOCKER, measured and now the only thing that matters here:** the client's
  `remoteplayer.dynamicslice` path never gets a `GameTransformComponent`. The Transform gate
  `FUN_141763b70` runs **30 times** per session and its registration (`FUN_141582430`) runs **0 times**,
  because the slice job's QueryInterface returns null for `{83482F97-84DA-4FD4-BF9E-7FE34C8E091F}`
  while accepting `{ED75FE05-…}` and `{B18D903B-…}` (= `ReflectContext`). The consequence is a **fixed
  26 warnings in every session since 2026-10-10**, independent of everything the server sends.
  **Both ways of supplying the missing Transform from outside the client have been measured and both
  break it**: handing a default-constructed component back from the lookup gave 26 warnings -> 0 but 26
  `The slice has more than one root` errors plus an APPCRASH (`0x3f00ce4`), and answering the
  QueryInterface gave `qi=2 answered=2` and an APPCRASH (`0x149923d`) before the world loaded.
  **So items 1 and 2 cannot be closed by the server in this build.** The remaining options are to
  provide a real client-side implementation of that interface (client modification, out of scope for a
  server-faithful implementation), or to re-scope both items to what the server can actually own.

### 2. Second player (after 1)

The client already renders remote players from `slices/remoteplayer.dynamicslice`; the work is a
server-side entity with its own state and an **AOI filter** so each client receives only nearby
entities. **Acceptance:** two clients see each other move.

### 3. Farming / gathering (parallel)

**RE-SCOPED 2026-10-19: there is no request to answer.** The premise ("decode its request from a live
session, answer it authoritatively") is refuted twice over:

- **Statically:** the whole Gathering/Gatherable family in the type table is **ClientFacet** (the SERVER
  calling the client) plus exactly one ServerFacet message, `SetStateDebugClient` (0x353), which is a
  debug setter. The Interactor family is territory governance, not world interaction.
- **Live, and decisively:** the operator walked to a plant and gathered, and the character **would not
  stop gathering**. Over that action the server received **exactly one** typed client message - `0x1910`
  (`TerritoryDetectorComponentServerFacet_AttemptTerritoryExit`) - and **zero** gathering types.

**Why the character never stops:** the client is the authority for gathering and repeats because
**nothing on the server side confirms or advances it**. That is the gathering analogue of the movement
finding, and it is the acceptance signal to use.

**New framing:** a gatherable's depletion has to be expressed in **replicated state**
(`GatherableControllerComponentReplicatedState` / `GatheringComponentReplicatedState`, both with
`InitializeReplicatedFields` in their ServerFacet) - the same record/fragment mechanism as the player's
position. **Acceptance:** a gathered node stops repeating the action because the server reflected the
state back.

### 4. The duration gate, still open and still blocking

**RE-SCOPED 2026-10-19: the teardown is NOT a fixed timer.** A probe-free session ran **1 h 24 min 06 s**
with `Disconnected from REP` 0, `is timeout` 0, `transportError` 0, `exiting to main menu` 0,
`ActorContainerDisconnect` 0 and `Cleanup()` 0 - **1053 s (17.5 min) past** the 1 h 06 min 33 s ending
measured on 2026-10-14, same build and same server code. So "find the 1 h 06 m timer" is the wrong
question; the item is now **"find what occasionally arms the teardown"**.

Two measurements narrow it: the four teardown anchors (`FUN_146420610`, `FUN_146444b10`,
`FUN_141004100`, `FUN_146460240`) recorded **zero hits** across 24 minutes of a clean session, and
`FUN_14643e4a0` is **not** the disconnect consumer (893 calls in 60 s with the watchdog returning
non-zero on all of them, and the session stayed up).

The 2-hour soak has still never passed, and it caps everything: a server that drops everyone after an
hour cannot be called usable. Soak runs must be **probe-free**. The 94-minute channel-1 collapse
(257-259 B → 68 B) remains a separate signal worth checking against the replication-counter varint
width.

**Operational note that cost a session 2026-10-19:** `OUTBOUND_PAYLOAD_LOG` hex-dumps every outbound
datagram, so `world.log` grew at **~1 MB/s** and one afternoon reached **7.3 GB** on a disk at 78%,
which made the client unresponsive and was briefly misread as a client bug. The verbose form is now
opt-in (`AZOTH_LOG_OUTBOUND_PAYLOADS=1`); all structured events stay on.

### 5. Start the Rust port — the trigger is now genuinely met

The ROADMAP's trigger was "the first behaviour the server decides rather than replays". That now
exists **twice**: the composed state bundle (2026-10-14) and the movement authority (today).

- **Start with `server/crates/protocol`**: port `varint`, `vlq32`, `bundle`, `frame`, `lz4` and the
  new `alc` movement reader, with a **byte-for-byte parity test against the Python encoders over the
  captured corpus**. That is the only genuinely port-ready piece and it does not displace the
  gameplay work.
- **Then port the movement authority** (`MovementValidator`, `DesyncTracker`, `CorrectionPolicy`,
  `YawAwareSimulator`) as a pure-logic crate with the same unit tests. It has no I/O, so parity is
  cheap to prove.
- **Do not port `rep.py` yet**: the replay pump and the response scheduler are scaffolding that will
  be replaced once the server owns world state.

### Known gaps that will bite, in the order they will bite

1. **`AZOTH_STATE_POSITION=sim` is verified live but not exercised by every run.** A 23 u walk tracked
   with 0 violations and 0 client errors (see DONE above), so the send path does carry it; what is
   missing is coverage of a run that changes the position mid-session rather than at spawn.
2. **The correction escalation fires only under a deliberate provocation.** It was measured live twice
   with `AZOTH_MOVEMENT_FORCE`, which is off by default, so a normal session exercises ACCEPT only.
3. **Intent (which keys are held) is still not decoded** — the body carries orientation and position,
   not input. Needed only for the server to *originate* movement, not to validate it.
4. **The 1 h 06 m teardown is still unexplained** (`SM_DISCONNECT`), and the 2 h soak is still the
   open acceptance gate for duration.
5. **`b` / pitch is decoded but unused**, deliberately: the wire is 2D.
- **Next, in order:** (1) capture a walking session and decode the intent flags; (2) the correction
  side — the server can already refuse, and the remaining work is to express that refusal on the
  wire.
- **A real server crash bug was fixed on the way (2026-10-18).** A local `import traceback` inside
  the feed-error handler made the name local for the whole function, so the tick-error handler
  raised `UnboundLocalError` instead of logging and **killed the world process** — three
  consecutive sessions never reached the world. Plausibly a contributor to older intermittent
  `transportError 4` runs. Acceptance for correction is unchanged: the client's accessor reports a
  position the server changes MID-SESSION.
- **The "load finished" signal is the input body growing, and it lands at 8-14 s, not 60.** The body
  grows `93 -> ... -> 154` bytes and only carries a position past ~280. A fixed 60 s grace period blinds
  the server for 45-50 s of a window in which the player is already controllable, and cannot tell a
  failed load from a slow one (one recorded session never produced a position at all). `LoadGate` keys
  on the marker. Acceptance: the validator starts at the measured transition instead of at a timer.

## Explicitly deferred

- A full 423k-function decompilation run is explicit via
  `python az.py re corpus`; setup never starts it in the background. The old
  per-user corpus is preserved locally as an archive, not input to the new workspace.
- Do not add a database, queue, fleet scheduler, content DSL, service split, or
  generic plugin system until an implemented feature or measured bottleneck
  requires it.
- Keep detailed protocol evidence in focused `research/docs/` references and
  `research/atlas/`; do not create a second task tracker for the same work.
