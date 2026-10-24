# Plan request — Azoth backend from zero, in Rust

You are planning. Produce a plan document. **Do not write implementation code yet.**

## Read first, in this order

- `AGENTS.md` — repository rules, evidence standards, and what must never be done.
- `docs/ARCHITECTURE.md` — intended Rust runtime shape and capacity gates.
- `docs/ROADMAP.md` — work order, and what is already known to be blocked.
- `STATUS.md` — current state of the world, newest first.
- `docs/EXTRACTION-2026-10-22.md` — what was extracted from the live official servers.
- `research/atlas/builds.json` — the installed client build, and which build every fact came from.
- `research/atlas/observed-endpoints.json` — the 75 endpoint families the real client requested.
- `research/atlas/presence-codecs.json` and `presence-live-capture.json` — actor-replication types and live payload captures.
- `services/gateway/src/` and `services/world/src/` — the working Python prototypes you are replacing.
  Read them to learn what the client requires. Do not copy their structure.

## The client you must serve

- Build **1.460.6033.6024067**, SHA-256 `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.
- Every fact here is build-scoped. A VA, offset or wire type from another build is **not** evidence.
- The client reaches `InGame` against the Python stack today. That is the floor, proven at the wire
  boundary, not asserted.

## What is being built — the whole thing

A **complete private server for a live-service MMORPG**, not a demo that satisfies a capture. Target:
full parity with everything the retail backend offered, and better performance than it.

In scope, none optional: identity and accounts; discovery; **content and assets** (CMS, news,
marketing tiles, images, **our own object storage**, our own privacy surface, entitlements);
**character lifecycle** (create from zero, persist everything, load, delete); **world entry**
(region → world routing, login queue, prologue, appearing); **living in the world** (levelling,
movement, combat, gathering, inventory, crafting, auction house, instance content); and
**operations** (gateway request logs, world monitoring, and eventually a **real-time 3D map** of the
world showing every player, NPC, enemy and gathering node, with the ability to observe and act).

Plan the whole shape; implement in phases; do not design something that must be thrown away.

## The discovery model is already region-shaped — use it, do not reinvent it

This is measured from the client, and it settles the region question.

The client fetches **one document** (the channel config, `STEAM_APP_ID.1063730.json`) whose
top-level keys are **regions**:

```json
{
  "channelName": "Azoth",
  "fra-prod": { "displayName": "EU Central", "poolId": "us-east-1:0de93f7c-…",
                "publicApis": [
                  {"clientTag": "authStack",              "apiEndpoint": "…"},
                  {"clientTag": "loginGateway",           "apiEndpoint": "…"},
                  {"clientTag": "JavelinGatewayServiceV2","apiEndpoint": "…"},
                  {"clientTag": "JavelinGatewayService-CF","apiEndpoint": "…"} ] },
  "gru-prod": { "displayName": "SA East", … },
  "iad-prod": { "displayName": "US East", … },
  "pdx-prod": { "displayName": "US West", … },
  "syd-prod": { "displayName": "AP Southeast", … },
  "platformMetadata": {…}, "omni": {…}, "omni.privacy-settings.*": {…}
}
```

And the world list carries each world's placement:

```text
everfall        regionId=fra-prod  worldSet=fra-prod  status=ACTIVE  repAddress=127.0.0.1:9000
windsward       regionId=gru-prod  worldSet=gru-prod  status=ACTIVE  …
```

**Consequences the plan must exploit:**

- A **region** is a key in that document with its own `publicApis` set. Each region can therefore be
  a **separate service with its own endpoint**, which is exactly the "mini-server per region" idea
  and it is what the client already expects.
- A **world** belongs to a region via `regionId` and to a pool via `poolId`. **Moving a world between
  regions is a change to its placement record**, not a code change.
- **Opening or closing a region at will is a change to that document** — so the channel document must
  be **served by our own service and generated from our own state**, never a static file checked
  into the repository. That single decision is what makes regions dynamic.
- Design the region as owning: its world directory, its players' session and identity context, and
  routing into a world. It must start, answer and survive with **no world up**.

## Decisions already made — design to these, do not re-litigate them

1. **Start from zero, in Rust.** Python stays runnable as the parity oracle.
2. **Port the gateway first** — entry point and smallest complete vertical.
3. **Login required.** Hardcoded credentials to begin with, but the model must grow into real
   registration without redesign. Hardcoded credentials are a seed, never a dead end.
4. **Nothing is cut.** We own the CMS, the news, the images, the object storage, the privacy
   surface, the databases.
5. **No dead code, no residue.** Every module states why it exists; anything that exists only to make
   a capture behave must say so and be justified, or be left out.
6. **Readable, agentic code.** Small files, clear names, comments that explain *why* and the
   non-obvious constraint — never a narration of the line. State the rule for what may enter the
   codebase, so it stays coherent as it grows.

## Research gathered — inputs, not things to re-derive

Disagree only with a stated reason, and say what the alternative buys **in this system**.

### Authority and the simulation loop
Decide where truth lives before anything else. The server owns authoritative world state; clients
propose inputs. That single decision simplifies anti-cheat, resolves conflicts consistently and
shrinks the exploit surface. Then decide how much to simulate: everything, or only what affects
fairness. The Python prototype already learned this: it is authoritative over movement and owns
inventory — keep that.

Advance the world in **discrete ticks at a fixed rate**, decoupled from wall-clock time, so all
participants share a frame of reference and the simulation does not drift. One tick runs
input → simulate → replicate. The tick reconciles three rates that must not be conflated: script
logic per frame, physics at a fixed delta, and replication often enough for smooth motion but small
enough to fit a real connection.

### Interest management (AOI) is the primary scaling lever
Replicating every object to every client wastes bandwidth and leaks information players should not
have. AOI gives each client a spatial subscription; only objects inside it are replicated. Common
implementations: fixed-size grid (simplest, cache-friendly), quadtree, or hierarchical AOI;
comparing them for large player counts is well studied. **Plan a grid first and make the subscription
boundary a first-class concept of the world model**, not an afterthought. A useful Rust reference for
the concept is Lightyear's replication "rooms": semi-static interest groups where an entity and a
client are relevant to each other when they share a room.

### Seamless world, partitions and handoff
The established pattern for a large contiguous world: a world server is the central authority over
**area/zone servers**; it assigns regions to them and coordinates movement of characters between
them. Partition the world spatially, distribute partitions across processes, let a player's interest
area decide which partitions matter.

The part that is usually gotten wrong, and which this project will hit because **the client already
performs zone transitions on fast travel**:
- A partition switch must be a **two-phase handoff**: a *prepare* phase that locks the migration
  intent and copies the necessary state, then a *commit* phase that switches authoritative ownership
  and notifies subscribers.
- The naive version — delete from A, create in B — works at walking speed and breaks on sprint,
  knockback, teleport or reconnect, producing double-writes or a gap where A still thinks it owns the
  player while B already accepts input.
- Keep a **single-writer** model per zone with a per-player **ownership epoch**, and put an **overlap
  zone** at borders where the old partition keeps arbitrating while the new one prewarms visibility
  and entities.
- Aim for **exactly-once input semantics** across the switch, and make a handoff that nobody confirms
  release itself, so a crashed handoff costs nothing.

### Dynamic capacity: opening and closing regions, placing worlds
The industry pattern for this is fleet orchestration (Agones is the reference implementation):
- A **fleet** is a named group of deployments; every game server in it registers with a **discovery
  service** and appears in live state **without heartbeat code of its own**.
- **Allocation** atomically claims a game server from a fleet matching a filter and returns its
  details; a claim nobody confirms **releases itself**, so a crashed handoff is free.
- Servers move through states (Ready → Allocated → …) and the allocator only hands out eligible ones.

Map that onto Azoth: a **region** is a fleet-like group, a **world process** is a game server that
registers itself with its region on start, and "open a region" / "move a world to another region" are
**registry and allocation operations**, not deployments. The plan must state how a world announces
itself, how a region decides a world is eligible, and what happens to players on a world that is
draining.

### Sessions and routing
- A session moves through **transport → authenticated → active → draining → closed**. Enforce an
  authentication deadline before application routes; keep liveness with heartbeats; close idle
  sessions after an idle timeout. Ticket expiry must not close an already authenticated session.
- On successful authentication, issue a **fresh reconnect ticket with an explicit expiry** and let
  the client keep only the latest.
- **The world server owns topology and placement.** Directories and gateways store committed location
  projections and cache forwarding routes — they are not a second topology authority.
- **Business traffic must go directly to the world.** A gateway hop on the data path adds latency at
  every packet and becomes a single point of failure. The gateway is for entry, not for gameplay.

### Persistence
- **Two logical databases**: identity/session (login) and world/player progression. Different load
  shapes, different lifetimes.
- **UUIDs for character ids**, not auto-increment, so ids stay stable across shards and migrations.
- Store big player aggregates as **compact binary blobs, not JSON** — JSON is too loose and too large
  for a hot persistence path.
- Keep a **write-through cache** in the game server so persistence is not on the tick path, without
  giving up integrity.
- **Real, versioned, forward-only schema migrations.**
- For anything economic, prefer an **append-only ledger** where a balance is a projection of the
  movements rather than a mutable column. That makes gold and item duplication auditable — the class
  of bug that ruins a private server's economy.
- De-normalisation is a deliberate performance tool. Say when you use it and why.

### Serialization for the hot path
`rkyv` gives zero-copy archived reads and is dramatically faster than `bincode`, `flatbuffers`,
`capnp` or JSON on read-heavy workloads; `bincode` is simpler and fine for cold paths. Note the real
trade-off: zero-copy archived formats are **not** friendly to schema evolution, so they are a poor
choice for **persisted** player state that must survive format changes, and an excellent choice for
**in-memory snapshots and replication payloads**. Pick per use, and say which and why.

### Rust async and the tick
The single most common failure: running blocking or CPU-heavy work on the async executor. Tokio
**cannot preempt** a task; a task that never yields starves everything else, and Tokio will not add
threads to compensate. Use `spawn_blocking` for blocking and CPU-bound work, keep the **simulation off
the network I/O plane**, and treat `Arc<Mutex<World>>` as the anti-pattern it is — that is what
collapses under load. Two viable simulation shapes: an **actor model** (each region/entity owns its
state, communicates by messages, no data race by construction) or a **data-oriented ECS** with systems
over partitioned entity sets. Choose one and justify it against AOI and the tick budget.

### Rust project organisation
A Cargo **workspace** with `[workspace.dependencies]` and `[workspace.lints]` so versions and lints are
declared once. Cargo imposes no layout for large workspaces, so the layout is a design decision you
must justify: **a crate owns a distinct reason to change**, not a folder. References: Microsoft's
Pragmatic Rust Guidelines (project section), matklad's "Large Rust Workspaces".

### Observability
Generic APM has no concept of a tick. What matters here:
- **Custom metrics that speak the game**: ticks per second, tick duration p50/p99, players online,
  per-player latency, entity counts, AOI subscription sizes, bytes sent per player.
- **Do not block the hot path to emit telemetry.** Use a batch processor with a bounded queue that
  **drops spans rather than adding latency**; head-sample high-frequency traces (order of 10%).
- **Cardinality discipline**: never put a player id or entity id in a metric label.
- Separate three things explicitly: **metric** (aggregate, cheap, always on), **log** (discrete event,
  structured and queryable, per-component target), **audit record** (who did what, append-only,
  never sampled).
- Profile with `perf` and flame graphs plus a frame profiler; do not guess where a tick goes.

## The gameplay transport is UDP/DTLS, direct to the world — measured, not assumed

From the live captures (`research/sessions/*/network/pktmon.analysis.json`):

```text
REP  192.168.50.12:27000  <->  35.71.153.244:53731
UDP · 125,485 packets · 34 MB · ~272 bytes/packet average
DTLS hellos 16 · DTLS records 125,485
world tick_hz 50.0
client -> server 13,186 packets; server -> client 42,377
```

**The gateway is HTTP/443 for entry only.** Once the client has a `RepAddress` all gameplay is UDP
straight to the world. The gateway leaves the data path, which is what the routing research says it
must do: a gateway hop adds latency to every packet and is a single point of failure.

### Hard constraints this puts on the Rust design

1. **DTLS in Rust is the project's biggest transport risk, and it must be settled before committing.**
   `rustls` does **not** implement DTLS — it exposes no DTLS primitives, and the ecosystem is explicit
   about it. The realistic options, and the plan must pick one **with evidence**:
   - `webrtc-dtls` (pure Rust): ~4.9M downloads, 183 dependents, but pre-1.0, a 34-crate dependency
     tree, and had a year-long gap without updates — a maintenance risk to measure, not assume.
   - `dtls` (the newer crate, 0.17.x): pure Rust, recent releases, fewer dependents — check its
     cipher-suite and server-side support against what the client offers.
   - `openssl` with the DTLS feature: mature, but a C dependency and `openssl-sys` build complexity.
   - `str0m` uses OpenSSL for DTLS today and has an open issue about replacing it with pure Rust,
     which is itself evidence that the pure-Rust path is not settled.
   **Compare them on: maintenance activity, server-side DTLS support, the cipher suites the client
   accepts, record-layer behaviour under loss, and build friction on Windows.** State the choice and
   the rejected alternatives.
2. **UDP gives no ordering and no delivery, so the protocol implements both.** The repository already
   proves this on the wire: an ACK window (`ack_window: 16384`), a per-session reliable-resend table,
   sequence numbers, and a replication gate that **discards** a counter that does not advance. Nothing
   may assume TCP semantics, and **every operation must be idempotent** because duplicates arrive.
3. **One socket, many peers.** The world uses a single UDP socket and demuxes by `(ip, port)` into a
   per-peer session. Keep that: one socket plus a map, **never one socket per player**. For scale,
   `SO_REUSEPORT` with several reader threads sharing the port is the documented next step — a single
   distributor task is a known bottleneck (Quilkin hit exactly this).
4. **Read in batches, process per tick.** One task per datagram collapses the scheduler at thousands of
   peers. Drain the socket into a bounded buffer, then run the tick over it. Prefer pre-allocated
   buffers: the reference UDP servers that reach millions of packets per second are zero-allocation
   after init.
5. **The DTLS handshake must never touch the tick.** Handshakes are expensive crypto; a player joining
   mid-tick must not stall a 20 ms budget. Handshake work goes to `spawn_blocking` or a dedicated
   thread, and the tick only ever sees established sessions.
6. **Datagram size is a design constant.** With DTLS overhead, stay under the path MTU (~1200 bytes);
   IP fragmentation makes loss catastrophic. The current replay chunk is 1100 bytes for exactly this
   reason.

### The replay is over — this is a real server now

State the difference plainly, because it changes what the code must do:

| | Python prototype today | What this plan builds |
| --- | --- | --- |
| State | replays 176 captured messages | **originates** it |
| Actors | one captured actor | N real actors with AOI |
| Movement | client simulates over recorded data | **server arbitrates** |
| Presence | does not exist | must **generate** the messages |

And the concrete blocker that follows: the six actor-replication codecs (`AddActorMessage` wire 449,
`SpawnActorsMsg` 574, `Replicate` 391, `ReplicateClient` 407, `FragmentUpdateMsg` 422, `UpdateMsg` 106)
are **identified but their layouts are not decoded** (`research/atlas/presence-codecs.json`). Without
those layouts the server cannot tell a client that another player exists. Decoding them is a live
instrumentation task, and `reverse/probes/client/frida-unmarshal.py` already works for it.

## 50 Hz, stable, with hundreds of players together — the performance contract

The world must run at a **fixed 50 Hz** (20 ms per tick) and stay stable with hundreds of players in
the same area. That is a contract, not an aspiration, and the plan must make it measurable.

### What the tick budget means

- 50 Hz means **20 ms per tick**, and everything in the tick must finish before the next fires.
  Overrun does not merely slow things down: updates bunch up and become bursty, and players see
  rubber-banding.
- **Keep tick work under ~50% of the budget** so an input spike has headroom. A tick that normally
  takes 19 ms has no headroom and is already broken.
- When a tick runs long the visible failure mode is a dropped frame: the loop wakes late, the rate sags
  below contract, and the effect compounds.
- **Split expensive per-entity work across frames** (round-robin AI, staggered AOI recomputation)
  rather than doing everything every tick.
- Use a **fixed timestep with a time accumulator**, so the simulation is deterministic and independent
  of how long the wall clock actually took. Ticks are a unit of simulation, not of real time.
- Measure with a **tick-time manager**: a rolling window of tick durations reporting mean, p50, p99 and
  overrun count. A server that cannot state its p99 tick time cannot claim 50 Hz.

### Where the cost actually is, and what the design must do about it

For hundreds of players in one area the dominant costs are, in order: **AOI recomputation**, then
**replication serialization**, then the network write. So:

- AOI must be **incremental**, not a full rebuild per tick: a player's subscription changes only when
  it crosses a cell boundary.
- Replication payloads are **serialized once and shared**, not re-encoded per recipient. This is where
  `rkyv`-style zero-copy snapshots pay for themselves: build the archived form once per tick per
  interest group.
- The egress path must be **batched per tick**, not per event, and must never block on the socket.

### The comparison the plan must include

The owner's requirement is that this is **faster, more modern, better maintained and more stable** than
what came before. A claim like that needs a method, so the plan must specify:

1. **A baseline measurement of the Python prototype** on the same machine: ticks per second achieved,
   tick duration p50/p99, bytes per player per second, and the player count at which it degrades.
   Without that baseline, "better" is unfalsifiable.
2. **A load harness** that drives synthetic clients through the real protocol — not a mock — stepping
   player count up in stages and reading the server's own metrics at each step: ticks per second, tick
   p50/p99, bytes sent, and the point where it falls behind.
3. **The acceptance criterion**: 50 Hz sustained, tick p99 under budget, at the stated player count, on
   the stated hardware. Name the hardware.
4. **A profiling story**: `perf` with frame pointers plus flame graphs, and a frame/tick profiler, so
   the answer to "why is the tick slow" is measured rather than guessed.

### Technology choices are themselves a decision to justify

The same requirement applies to every dependency the plan proposes — transport, async runtime,
serialization, database driver, HTTP stack. For each, state: **why this one**, what its maintenance
and release cadence look like, what it costs (dependency tree, C dependencies, build friction on
Windows), and what was rejected. A choice that cannot be justified against "more modern, better
maintained, more stable" is not a choice, it is a habit.

## Constraints

- Do not invent protocol facts. An unrecorded client requirement is an **open question phrased as a
  measurement**, never a guessed shape.
- Keep the Python stack runnable; the port is compared against it at the wire boundary.
- Steam install is read-only. No process memory reads, no debugger, no injection, never against the
  official servers.
- Code, comments, docs and commit messages in English.
- Performance target: **better than the original**. Name where the original was slow or wasteful and
  how this design beats it. No number without a measurement plan.

## What the plan must contain

1. **Scope and non-goals**, with the process boundary between channel service, region and world.
2. **Crate and module layout** under `server/`, one sentence each on what it owns and why it is
   separate; plus the stated rule that keeps files small and the codebase coherent.
3. **Domain model** — account, session, character, region, world, partition, entity, item, currency —
   and which component owns the authoritative copy of each.
4. **Discovery design** — how the channel document is **generated from live state**, how a region is
   opened and closed at runtime, how a world registers itself with a region, and how a world is moved
   between regions without a redeploy.
5. **Full endpoint inventory** grouped by purpose (identity, discovery, content/assets, character,
   queue, world entry), each with the client need, the evidence, and whether the shape is known or
   open. Start from `research/atlas/observed-endpoints.json`; include everything the client needs.
6. **Identity, session and character lifecycle** — registration, login, tokens, session states,
   reconnect tickets, and create → persist → load → delete for a character.
7. **Region and world model** — ownership, eligibility, routing, draining, and independent failure.
8. **Simulation model** — tick rate and budget, authority boundaries, the AOI design (grid vs
   quadtree, cell size, subscription radius, update policy), and the **partition handoff protocol**
   with its prepare/commit phases, ownership epoch and overlap zone.
9. **Persistence design** — the two databases, migrations, the blob format and its evolution strategy,
   the write-through cache, and whether economic state is a ledger.
10. **Serialization choices** per use (hot path, replication, persistence) with the trade-off stated.
11. **Wire model strategy** — how the client's exact JSON shapes are represented so a field cannot
    drift silently, and how byte-level parity with Python is proven.
12. **Observability and operations** — event schema, per-component targets, metric/log/audit split,
    sampling and cardinality rules, and how the 3D map and world monitoring consume it **without
    touching the hot path**.
13. **The 3D real-time map** — the data the simulation must expose, the transport to the viewer, and
    why it costs nothing when nobody is watching.
14. **Port order** — phases, each independently verifiable, each with an acceptance criterion as an
    observable client or wire result; what is deferred and why.
15. **Test strategy** — unit, fixture-driven wire parity, load/capacity, and what only the real client
    can prove.
16. **Open questions** — phrased as measurements someone can run.

## Output

Write the plan to `docs/PLAN-backend-rust.md`. Be specific to this repository and this client build.
Every claim about the client must trace to a file here or be marked an open question. Where you apply
a practice from the research above, say what it buys **in this system** and what it costs.
