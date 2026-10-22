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
