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

### 2. Resolve the current client blocker — **BOTH GATES MET 2026-10-13**

- **Movement gate: MET.** The local transform changes while W is held and is still when no input is
  given, measured with the client's own accessor and reproduced three times (net 83.026 u and 20.784 u
  of displacement in two runs; 0.0 u with no input). A one-variable A/B settles the cause: with the
  state stream **OFF** the position is frozen at the historical constant
  `(9343.6416, 2786.7327, 87.538)` and W does nothing; with it **ON** the player moves.
  The missing piece was **record id 1**, the local player's own AOI state, which the stream's old
  floor of `0xA0` never sent. See `MOVEMENT_WORKS_state_stream_enables_player_simulation_20261013`.
- **Connection gate: the HUD cable is CLEARED.** The same A/B shows the icon **absent** with the
  stream on and **RED (3.7%)** with it off, and the ALC stamp it ages goes from frozen (growing to
  262 s) to refreshing 225 times in 140 s with a maximum age of 100 ms. See
  `RED_CABLE_FIXED_record1_state_stream_refreshes_the_alc_stamp_20261013`.
- **What remains for this gate:** duration. Movement was measured in 10-12 s windows inside sessions
  that lived ~22 min; there is no 30-minute proof and no 2-hour soak yet, and the sessions still end on
  a client crash. The last crash was `frida-agent.dll` at `0x9c7f4` caused by a measurement probe, so
  soak runs must be probe-free.



- Treat this as two separate acceptance gates. REP transport survived a 2 h 06
  run with no transport disconnect, but the player still sees a red ALC/HUD
  warning and the client has a measured ~20-minute return-to-menu path. That path is
  now measured to be **armed by the replay gap**: `AZOTH_CHUNK_GAP_MS=20` (replay 29 s)
  armed the teardown delegate at 20:00.398, while the 4 ms default (replay 10 s) did not
  arm it at all. The corrected patch (`0x14100425F`) is exercised and does suppress
  `exiting to main menu`/`Cleanup()`, but it is **not a session fix**: the same delegate
  already tears the connection down at `0x141004230` before the patched call. Preventing
  the arm is the real work. See `exitA_gap20_run_outcome_20261011` and
  `chunk_gap_decides_the_20minute_arm_20261011`. Transport uptime alone does not close
  user-visible connection stability, and no run has reached 30 minutes.
- **Connection gate:** trace the producer/consumer for the ALC input stamp
  (`+0xAA8`) and door (`+0xAA0`). The stamp currently stops updating and the door
  stays closed; `StartMovementCommunicationMsg` and replayed input responses did
  not open it. Change one evidence-backed server behavior per fresh client.
  Acceptance: the real HUD warning clears and stays clear, REP has no transport
  error/disconnect, and the client remains in-world past the 20-minute exit
  threshold. First prove this for 30 minutes, then run a 2-hour soak.
- **Movement gate:** the local transform is now measurable with the client's own accessor:
  `nw_getPlayerPosition`'s handler (`0x141015b30`) calls `FUN_140fddfa0(&holder)` and reads
  `*(float*)(holder+0x14c/0x15c/0x16c)`. Probe `frida-player-position.py`, validated against
  the client's own command output by `frida-position-validate.py`. Measured 2026-10-12:
  **667/667 identical samples** over 136 s containing a 10 s W hold and a 4 s S control,
  while the server received 7804 channel-1 records — so W does not move the player and the
  input does reach the game. **Re-confirmed the same day on a session that provably
  rendered the possessed player** (world visible, full HUD, `verdict: InGame reached, player
  possessed`): position `(9343.6416, 2786.7327, 87.538)` unchanged through a 10 s W hold and
  a 5 s S control while the server received 20 channel-1 records per second at every
  timestamp bucket. The negative half of the movement criterion therefore no longer rests
  on a black-screen session. Evidence:
  `movement_negative_confirmed_on_a_rendering_session_20261012`, capture
  `research/sessions/session-20261012T1818Z-render-ok/`.
- **The position arrives as REPLICATED STATE, not as an RMI — and the "facets are missing" reason was
  WRONG (corrected 2026-10-12).** `PlayerPositionTrackingComponent` has only AI spawn-manager debug
  messages; `PositionInTheWorldComponent{Client,Server}Facet` have none; and
  `PositionInTheWorldComponentServerFacet::InitializeReplicatedFields` exists with
  `MB::PositionInTheWorldReplicatedState`. So no RMI can be the authoritative path, and "do not write
  another position RMI payload" stands. **But the stated blocker does not:** measured on the live
  local-player entity, **110 of 126 components have a bound client facet at `component + 0x80`**, 106 of
  106 named ones are `*ClientFacet`, and `PlayerPositionTrackingComponent` — the one position component
  that *is* on the entity — **has its `PlayerPositionTrackingComponentClientFacet` bound**. The earlier
  "ALL ABSENT" list searched the entity's **component list** for facet class names, and `IPositionReceiver`
  is an **interface**, not a component: three kinds of object were conflated. `PositionInTheWorldComponent`,
  `PositionalTicketingComponent` and `CameraComponent` genuinely are not components of this entity, and
  there is no `GlobalStorage` component either — which is also why the 23
  `GlobalStorageComponentClientFacet` errors appear (a class absent from *this* entity), not a broken facet
  mechanism. Evidence: `client_facets_ARE_bound_on_the_live_player_entity_20261012`.
- **What creates a client-side facet, and why the factories are never called directly (2026-10-12).**
  Facets are built by per-class **by-name factories** against the global reflection registry at
  `0x14a313ff8` — the same registry that backs `IPositionReceiver`'s register-by-name/installer — and the
  result is stored at `component + 0x80`. The factories sit in `.rdata` tables with the tail
  `[0x1406c7b30][0x1416a1340][FACTORY][0x14171a8b0][0x1417aae90]`; scanning it yields **368 distinct
  `*ComponentClientFacet` classes**, regenerated by `reverse/tools/scan-client-facets.py --check` into
  `research/derived/client-facet-factories.json`. The factories have **zero direct callers** — the address
  exists only as a table slot — so creation is table-driven; the family creators `0x142d14d50` and
  `0x145c94990` are likewise unreferenced directly. Since the facets demonstrably DO get bound, the
  invoker is working; it is not the blocker.
- **Next measurement (revised).** Not facet creation. Either (a) check whether `PositionInTheWorldComponent`
  is supposed to be on the entity, by inspecting a *remote* player's entity (which does replicate a
  position) and seeing whether that component is on it; or (b) instrument what the live
  `PlayerPositionTrackingComponentClientFacet` does with the 20 Hz channel-1 input stream. Attach at
  character select and prefer hooks-only: a probe that hooks the hot component lookup and then detaches
  killed the client **three times** in one session (`frida_agent_unload_crash_reproduced_20261012`).
- **The replay provably never carries the position.** The measured live position appears nowhere in any
  of the replay's 177 messages in float32, float64, or int16/int32/int64 fixed point. The spawn record
  (`record_id 1`, 48 fragments, 46393 B) carries the player's actor id but not the position, and only 48
  of the entity's 126 components have a fragment at all.
- **The world only renders when the runbook env vars are exported (2026-10-12).** `python az.py dev`
  forwards `AZOTH_*` from the calling shell, and `AZOTH_REPLAY_LOCAL_PLAYER_UUID` defaults to `off` — the
  documented failing value. Without it the world is **black**, `Exceeded max recursion for deferred
  actions` appears 5 times even though the predicate patch is correctly applied, the
  `replay-local-player-uuid` spans filled is 0, and the client sends 0 channel-1 records. Verify the
  effective config with the world server's `config` event before interpreting client behaviour.
  Evidence: `runbook_env_vars_are_mandatory_and_verifiable_20261012`.
- **Physics components are absent on the live player entity (RESOLVED 2026-10-12).** Three
  instants of the same entity all show 126 components with `CharacterPhysicsComponent` and
  `GameRigidBodyComponent` absent and the controls present, and the ADD hook was live (24 adds,
  none on the player entity). The old record misread its own capture
  (`physics_components_absent_RESOLVED_20261012`).
- Resolve the two known application failures with evidence. W produces no movement-family
  message (re-confirmed 2026-10-12 on a fresh client: a 4 s W-hold produced 210 inbound
  app-data records, all channel 1 at 119/120 B), while the client does stream its input
  ~20×/s: wire `0x635` is `ActionListComponentServerFacet_ReceiveInputFromClient`, so the
  input direction works. The reliable-4216 dispatch failure is a **wrong target id**, and
  the previously reported re-addressing fix was a **false fix**: the working blob is the
  client's `TimeComponentClientFacet` local id, so the position goes to a time-sync facet.
  The client implements `IPositionReceiver` (vtable `0x1482eb160`) but **no client-side RMI
  target is an instance of it** (37063 targets, 225 vtables, 0 positives). Find what
  constructs and registers that instance, and what tells the server its local id.
  `StartMovementCommunicationMsg` is measured not to bind it, even reliable on channel 0.
- **Movement acceptance:** the local transform changes in the expected direction
  while W is held, stops when released, and produces the expected client/server
  movement exchange. Use the client's own position accessor as the primary proof
  (`frida-player-position.py`); screenshots are supporting evidence only. Then exercise
  turning and collision and record the authoritative server checks. Note the measured
  negative already on record: with the current server behaviour the position does not
  change at all while W is held, and the `IPositionReceiver` instance the reply needs is
  never created client-side.
- **Open question to settle before it steers work:** whether the live player entity
  carries `CharacterPhysicsComponent` / `GameRigidBodyComponent`. **SETTLED 2026-10-12: it does
  not.** Three instants of the same entity, with a live ADD hook, all show both absent and the
  controls present; the earlier claim misread its own capture
  (`physics_components_absent_RESOLVED_20261012`). Do not build a plan on physics components
  being present.
- Reproduce each baseline on a fresh `NewWorld.exe`; change one variable per
  attempt. Record build hash, config, logs/probe counters, HUD result, transform
  delta, duration, and negative results in the atlas before closing the run. Keep
  Frida attaches out of the baseline runs: a read-only probe is a measured
  confounder for this client (a 25-minute session crashed with `0xc0000005` in
  `ntdll.dll` ~40 s after one detached).
- Implement only the protocol behavior those measurements establish in the
  Python prototype; preserve fixtures and observed outcomes for the later Rust
  port. Do not estimate a finish date until the ALC and movement call paths are
  identified.

### 3. Complete the client-visible server contract

- **The outbound half is measured and request-correlated (2026-10-14).** Captured typed
  responses are sent only when the client sent the request they answer; see
  [INBOUND-REQUESTS.md](../research/docs/INBOUND-REQUESTS.md) and `AZOTH_REPLAY_REQUEST_GATING`.
  Verify a change to the map with `python scripts/request-response-map.py --check`.
- **Next: the inbound dispatcher.** There is still no inbound typed-message dispatcher, so all
  19 requests a session sends are acknowledged at the transport level and ignored. Answer the
  five a playable world needs, in order: `PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient`
  (2515), `ObjectivesComponentServerFacet_UpdateTrackedObjectives` (1458) /
  `..._SetObjectiveAutoPinning` (2709), `ContractsComponentServerFacet_LookupContractsByParticipant`
  (2556, whose `0x08E6` response the capture already contains),
  `GlobalStorageComponentServerFacet_SetReplicateStorage` (387), and
  `TimeComponentServerFacet_SyncToClient` (4248).
- Let new client requests and failed state transitions set the next protocol
  work item; record exact fields and evidence in the atlas.
- Keep the gateway and world process boundaries until measured requirements
  call for a different deployment shape.

### 4. Port understood behavior to Rust

- Start the workspace when the first behavior is ready to port, not as empty
  scaffolding.
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
