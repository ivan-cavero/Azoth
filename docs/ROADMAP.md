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
- **Next: the inbound dispatcher.** There is still no inbound typed-message dispatcher, so every
  request the client sends is acknowledged at the transport level and ignored — measured **19** in a
  short session and **29** in one that exercises more UI, with the server logging one
  `inbound-request-coverage` line per session that splits them into `answerable_by_replay` and
  `no_replay_response`. Answer the five a playable world needs, in order: `PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient`
  (2515), `ObjectivesComponentServerFacet_UpdateTrackedObjectives` (1458) /
  `..._SetObjectiveAutoPinning` (2709), `ContractsComponentServerFacet_LookupContractsByParticipant`
  (2556, whose `0x08E6` response the capture already contains),
  `GlobalStorageComponentServerFacet_SetReplicateStorage` (387), and
  `TimeComponentServerFacet_SyncToClient` (4248).
- Let new client requests and failed state transitions set the next protocol
  work item; record exact fields and evidence in the atlas.
- Keep the gateway and world process boundaries until measured requirements
  call for a different deployment shape.

### 4. Port understood behavior to Rust — the trigger is authority, not calendar

- Start the workspace when the first behavior is ready to port, not as empty
  scaffolding.
- **Assessed 2026-10-14: not yet, and the reason is specific.** The server today is a faithful
  **replayer**, not an authoritative game server: the player moves because the CLIENT simulates
  from the captured record-1 state we stream, so the server does not decide the player's position.
  Rust exists here to reach 2,500 then 10,000 concurrent players, which is a **simulation** target
  that cannot even be expressed while there is no authoritative simulation to port.
- **What IS ready to port** (measured, fixtured, and stable): the wire codecs (`varint`, `vlq32`,
  `bundle`, `frame`, `lz4`) and the DTLS/Carrier/V3 connection path. They have round-trip tests
  against the captured corpus.
- **What is NOT ready:** the replay pump and the response-scheduling policy, which are scaffolding
  that will be replaced once the server owns the world state; and anything in
  `services/world/src/azoth_world/rep.py` that exists to make a capture behave.
- **Trigger:** the first behavior the server decides rather than replays — i.e. the first inbound
  request it answers with its own authoritative effect (section 3). Port that, not the scaffolding.
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
