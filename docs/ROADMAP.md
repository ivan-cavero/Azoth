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

- Trace why the client does not create and attach the local player's movement
  components, starting from the confirmed `transform_spawner_chain` findings.
- Pick one evidence-backed variable per fresh-client attempt. Stop revisiting
  input focus, camera delivery, and Carrier pacing unless new evidence reopens
  those boundaries.
- Implement the observed protocol behavior in the Python prototype and preserve
  a fixture or measured client result for the Rust port.

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
