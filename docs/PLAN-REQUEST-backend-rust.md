# Plan request — Azoth backend from zero, in Rust

You are planning. Produce a plan document. **Do not write implementation code yet.**

## Read first, in this order

- `AGENTS.md` — repository rules, evidence standards, and what must never be done.
- `docs/ARCHITECTURE.md` — the intended Rust runtime shape and the capacity gates.
- `docs/ROADMAP.md` — work order, and what is already known to be blocked.
- `STATUS.md` — current state of the world, newest first.
- `docs/EXTRACTION-2026-10-22.md` — what was extracted from the live official servers.
- `research/atlas/builds.json` — the installed client build, and which build every fact came from.
- `research/atlas/observed-endpoints.json` — the 75 endpoint families the real client requested.
- `research/atlas/presence-codecs.json` and `presence-live-capture.json` — the actor-replication
  message types and the live payload captures.
- `services/gateway/src/` and `services/world/src/` — the working Python prototypes you are
  replacing. Read them to learn what the client requires. Do not copy their structure.

## The client you must serve

- Build **1.460.6033.6024067**, SHA-256 `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.
- Every fact in this repository is build-scoped. A VA, offset or wire type from another build is
  **not** evidence for this one.
- The client reaches `InGame` against the Python stack today. That behaviour is the floor the Rust
  backend must preserve, proven at the wire boundary rather than asserted.

## What is being built — the whole thing, not a slice

This is a **complete private server for a live-service MMORPG**, not a demo that satisfies a
capture. The target is full parity with everything the retail backend offered, and then better
performance than it.

That includes, and none of this is optional:

- **Identity and accounts**: registration, login, sessions, tokens, entitlements, privacy settings.
- **Discovery**: channel config, region list, world list, CMS/news content, marketing tiles,
  images, S3-style asset fetches.
- **Character lifecycle**: create a character from zero, persist it, load it, delete it. Everything
  a character owns must survive a server restart: appearance, progression, inventory, currency,
  position, quest state, housing, everything the client can hold.
- **World entry**: region → world routing, the login queue, the prologue/first-light experience,
  appearing in the world, and then living in it: levelling, movement, combat, gathering,
  inventory, crafting, the auction house, and the instance content.
- **Operations**: monitor and act on the running system — gateway request logs, world monitoring,
  and eventually a **real-time 3D map of the world** showing every player, NPC, enemy, gathering
  node and interactable, with the ability to observe and intervene from the server side.

Plan the whole shape. Implement in phases. But do not design something that has to be thrown away
to reach the parts listed above.

## Decisions already made — design to these, do not re-litigate them

1. **Start from zero, in Rust.** The Python stack stays runnable as the reference implementation
   and the parity oracle while the Rust one is built.
2. **Port the gateway first**, because it is the entry point and the smallest complete vertical.
3. **Login is required.** Credentials may be hardcoded to begin with, but the model must grow into
   real registration without redesign: accounts, credential storage, sessions, token issuance.
   Hardcoded credentials are a seed, never a dead end.
4. **Hierarchy: Region → World.**
   - A **region** is a small service that knows which worlds exist, holds its players' session and
     identity context, and routes a player into a world.
   - A **world** is the authoritative game server for that region.
   - The split must be real: a region starts, answers, and survives with no world up; a world does
     not need to know about other regions.
   - Note a known tension to resolve with evidence, not assumption: the **client** knows a channel
     config with a region list and a `RepAddress` per world. Your region concept has to map onto
     what the client actually asks for. If that means the region is really a directory and session
     service rather than a game server, say so plainly and justify it from the client's requests.
5. **Nothing is cut.** CMS, news, S3, images, privacy, entitlements are **in scope**. The goal is to
   own all of it: our own object storage for images, our own databases, our own privacy surface.
6. **No dead code and no residue.** Every module states why it exists. Anything that exists only to
   make a capture behave must say so and be justified, or be left out.
7. **Readable, agentic code.** Small files, clear names, comments that explain *why* and the
   non-obvious constraint, never a narration of what the line does. A rule in the plan for what is
   allowed to enter the codebase, so it stays coherent as it grows.

## Research already gathered — treat as inputs, not as things to re-derive

The following was researched for this plan. Cite it, apply it, and disagree with it only with a
reason.

**Server authority and state.** Decide where truth lives first. In a competitive online game the
server owns authoritative world state and clients only propose inputs; that single decision
simplifies anti-cheat, resolves conflicts consistently, and shrinks the exploit surface. Then
decide how much to simulate: full physics and collision, or only the parts that affect fairness.
The existing Python prototype already learned this the hard way — it is authoritative over player
movement and owns inventory, and that is the behaviour to keep.

**Interest management (AOI) is the primary scaling lever.** Sending every object to every client
wastes bandwidth and leaks information players should not have. AOI gives each client a spatial
subscription; only objects inside it are replicated. The common implementations are a fixed-size
grid over the world, a quadtree, or hierarchical AOI. Comparing algorithms for large player counts
is a well-studied problem — plan for a grid first (simplest, cache-friendly, easy to reason about)
and make the subscription boundary a first-class concept in the world model, not an afterthought.

**Seamless-world / sharding patterns.** For a large contiguous world with high population, the
established patterns are: partition the world spatially, distribute those partitions across
processes, and let a player's interest area decide which partitions matter. Plan for the world
process to own *partitions* with an explicit hand-off boundary, even if the first implementation
runs them in one process. That is the difference between a design that scales and one that has to
be rewritten.

**Concurrency model.** Two viable shapes: an actor model (each entity or region owns its state and
communicates by messages, so no data race by construction), or a data-oriented ECS with systems
running over partitioned entity sets. For a tick-based simulation with AOI, the practical
consensus is: keep the **game loop isolated from network I/O**, use `tokio` for the I/O plane, and
use either actors or ECS for the simulation plane. Do not put an `Arc<Mutex<..>>` around the world
and call it done; that is the pattern that collapses under load. `tokio` is the right async runtime
for the I/O side because of ecosystem maturity and TCP/runtime tooling.

**Persistence.** Established MMORPG practice, all of it relevant here:
- Use **two logical databases**: one for identity/session (login), one for world and player
  progression. They have different load shapes and different lifetimes.
- Use **globally unique character ids** (UUIDs), not auto-increment integers, so ids are stable
  across shards and migrations.
- Store player progress as **compact binary blobs** for the big aggregates, not JSON. JSON is too
  loose and too large for a hot persistence path.
- Keep a **write-through cache** in the game server so persistence does not sit on the tick path,
  while keeping data integrity.
- Use **real schema migrations**, versioned and forward-only, not "run this script by hand".
- For anything economic, consider an **append-only ledger** where a balance is a projection of the
  movements rather than a mutable column. That makes gold and item duplication auditable, which is
  exactly the class of bug that ruins a private server's economy.
- De-normalisation is a deliberate performance tool, not an accident. Say when you use it and why.

**Rust project organisation.** Use a Cargo **workspace** with `[workspace.dependencies]` and
`[workspace.lints]` so versions and lints are declared once. Cargo does not impose a layout for
large workspaces, so the layout is a design decision you must justify: a crate must own a distinct
reason to change, not mirror a folder tree. Reference: Microsoft's Pragmatic Rust Guidelines
(project section) and matklad's "Large Rust Workspaces".

## Constraints you must respect

- Do not invent protocol facts. If the client's requirement for an endpoint is not in the atlas,
  mark it an open question for measurement rather than guessing a shape.
- Keep the Python stack runnable; the port is compared against it at the wire boundary.
- The Steam install is read-only. No process memory reads, no debugger, no injection, and never
  against the official servers.
- Code, comments, documentation and commit messages in English.
- Performance target: **better than the original**. State where the original was slow or wasteful
  and how the design beats it. Do not claim a number without a measurement plan.

## What the plan must contain

1. **Scope and non-goals** — what the backend owns end to end, and explicitly what it does not.
   Include the boundary between gateway, region and world processes.
2. **Crate and module layout** under `server/`, one sentence each saying what it owns and why it is
   separate. Justify every boundary. Name the rule that keeps files small and the codebase coherent.
3. **Domain model** — account, session, character, world, region, entity, item, currency. Say which
   component owns each, and where the authoritative copy lives.
4. **The full endpoint inventory** grouped by purpose (identity, discovery, content, character,
   queue, world entry), each with the client need it satisfies, the evidence it is required, and
   whether its exact shape is known or open. Start from
   `research/atlas/observed-endpoints.json` and include everything the client needs — nothing is
   cut for brevity.
5. **Identity, session and character lifecycle** — registration, login, token issuance, how a
   session travels from gateway to region to world, and character creation → persistence → load.
6. **Region and world model** — what each owns, discovery, routing, and how they fail independently.
7. **Simulation model** — tick budget, authority boundaries, what is simulated server-side, and the
   **AOI design** (grid vs quadtree, cell size, subscription radius, update policy).
8. **Persistence design** — the two databases, schema and migration strategy, the blob format for
   player state, the write-through cache, and whether economic state is a ledger.
9. **Wire model strategy** — how the client's exact JSON shapes are represented in Rust so a field
   name or type cannot drift silently, and how byte-level parity with the Python output is proven.
10. **Observability and operations** — the event schema, per-component log targets, what is a metric
    versus a log versus an audit record, and how the future 3D map and world monitoring consume it
    **without touching the hot path**. Legible and queryable; not console spam.
11. **The 3D real-time map** — the data the simulation must expose for it to exist (entity
    positions, types, states), the transport to the viewer, and why it costs nothing on the tick
    path when nobody is watching.
12. **Port order** — phases, each independently verifiable, each with an acceptance criterion
    expressed as an observable client or wire result. Name what is deferred and why.
13. **Test strategy** — unit, fixture-driven wire parity, load/capacity, and what can only be proven
    with the real client.
14. **Open questions** — phrased as measurements someone can run, never as guesses.

## Output

Write the plan to `docs/PLAN-backend-rust.md`. Be specific to this repository and this client build.
Every claim about the client must trace to a file here, or be marked an open question. Where you
recommend a practice from the research above, say what it buys **in this system** and what it costs.
