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

### 2. Resolve the current client blocker

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
  input does reach the game. Build the next step on `PlayerPositionTrackingComponent` /
  `PositionInTheWorldComponent`, NOT on the `ActorMover` family: that family is server-side
  hub migration (`Sending CommitMovement for actor`, `DelayMigrationsMsg`), which is why
  `StartMovementCommunicationMsg` changed nothing. The client's own accessor also gives
  turning/collision checks a real instrument.
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
  carries `CharacterPhysicsComponent` / `GameRigidBodyComponent`. The 2026-10-10 record
  says yes; a 2026-10-12 measurement of the same lookup on the same 126-component entity
  says no, and the full 126-component list dump does not contain them
  (`physics_components_absent_on_the_live_player_entity_20261012`). Settle it by
  re-dumping at spawn+4 s / +30 s / +2 min while logging every ADD (`FUN_1413789c0`),
  and do not build a plan on either answer until then.
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

- Let new client requests and failed state transitions set the next protocol
  work item; record exact fields and evidence in the atlas.
- Finish the state and replication path needed for movement before expanding
  unrelated systems, persistence, or infrastructure.
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
