# Plan request — Rust gateway from zero (Azoth)

You are planning, not implementing. Produce a plan document. Do not write code yet.

## Read first (in this order)

- `AGENTS.md` — repository rules, evidence standards, and what must never be done.
- `docs/ARCHITECTURE.md` — the intended Rust runtime shape and the capacity gates.
- `docs/ROADMAP.md` — work order, and what is already known to be blocked.
- `STATUS.md` — the current state of the world, newest first.
- `docs/EXTRACTION-2026-10-22.md` — what was extracted from the live official servers.
- `research/atlas/builds.json` — the installed client build and which build every fact was measured on.
- `research/atlas/observed-endpoints.json` — the 75 endpoint families the real client actually requested.
- `services/gateway/src/` — the working Python prototype you are replacing. Read it to learn
  what the client requires; do not copy its structure blindly.

## The client you must serve

- Build **1.460.6033.6024067**, SHA-256 `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.
- Every fact in this repository is build-scoped. A VA, offset or wire type from another build is
  not evidence for this one.
- The client reaches `InGame` against the Python stack today. That is the behaviour the Rust
  gateway must preserve, verified at the wire boundary, not by assertion.

## What the gateway is, in this project

It is the HTTP surface the client contacts **before** it joins a world. It answers the channel
config, the Omni token exchange, the credential and login surfaces, `getlogininfo`, the login
queue, character metadata, entitlements, privacy settings, CMS/news content, and S3-style
fetches. Once the client has a `RepAddress`, it leaves the gateway and talks to a world server
over UDP/DTLS.

**The gateway must serve exactly what the client needs and nothing else.** No speculative
endpoints, no "just in case" routes, no dev or research surfaces in the runtime binary.

## Decisions already made by the owner — design to these, do not re-litigate them

1. **Start from zero, in Rust, and port the gateway first.** The world server comes later.
2. **Login is required.** For now credentials are hardcoded, but the design must accommodate
   real registration later: accounts, stored credentials, sessions, tokens, and the fact that a
   player will eventually create their own account. Do not design a scheme that hardcoded
   credentials make impossible to grow.
3. **Hierarchy: Regions → Worlds.**
   - A **region** is a small server process that knows which worlds exist in it, holds its
     players' session/identity context, and routes a player to a world.
   - A **world** is the main game server for that region and owns the authoritative simulation.
   - The split must be real: a region must be able to exist, start, and answer without a world
     being up, and a world must not need to know about other regions.
4. **Behave like a real MMORPG backend**, not like a script that satisfies a capture. That means
   explicit domain boundaries, typed wire models, real error handling, and state that is owned
   by exactly one component.
5. **No dead code and no residue.** Every module must have a stated reason to exist. If a piece
   only exists to make a capture behave, say so and justify it or leave it out.
6. **Future requirement to design for, not to build now:** a real-time 3D map that monitors a
   running world — every player moving, NPCs, enemies, gathering nodes, everything — with the
   ability to observe and act on it from the server side.
7. **Future requirement to design for:** observability that is legible. Structured, queryable
   logs per component; gateway request logs; world monitoring. **Not** thousands of lines
   scrolling in a console. Design the log/metric/trace shape now even though the dashboards come
   later.

## Constraints you must respect

- Do not invent protocol facts. If the client's requirement for an endpoint is not recorded in
  the atlas, mark it as an open question for measurement rather than guessing a shape.
- Keep the Python stack runnable while the Rust one is built; the port must be comparable
  against it at the wire boundary.
- The Steam install is read-only. No process memory reads, no debugger, no injection, and never
  against the official servers.
- Follow the repository's artifact rules: code, comments, docs and commit messages in English.

## What the plan must contain

1. **Scope statement** — what the gateway is responsible for, and explicitly what it is not.
   Include the boundary against the region and world processes.
2. **Crate/module layout** under `server/`, with one sentence per crate or module saying what it
   owns and why it is separate. Justify every boundary; do not mirror folders.
3. **The endpoint inventory you will implement**, grouped by purpose, each with: the client need
   it satisfies, the evidence it is required, and whether its exact shape is known or open.
   Start from `research/atlas/observed-endpoints.json` and cut anything the client does not need.
4. **Identity and session model** — accounts, credentials, login, token issuance, how a session
   is carried from gateway to region to world, and how hardcoded credentials are a seed rather
   than a dead end.
5. **Region and world model** — what a region owns, what a world owns, how they are discovered,
   how a player is routed, and how the two fail independently.
6. **Wire model strategy** — how the client's exact JSON shapes are represented in Rust so a
   field name or type cannot drift silently, and how parity with the Python output is proven.
7. **Observability design** — the event schema, log levels, per-component targets, what is a
   metric versus a log versus an audit record, and how the future 3D map and world monitoring
   will consume it without changing the runtime's hot path.
8. **Port order** — a sequence of phases, each independently verifiable, each with an acceptance
   criterion expressed as an observable client or wire result. Name what is deliberately
   deferred and why.
9. **Test strategy** — what is a unit test, what is a fixture-driven wire parity test, and what
   can only be proven with the real client.
10. **Open questions** — the things you could not settle from the repository, each phrased as a
    measurement someone can run, not as a guess.

## Output

Write the plan to `docs/PLAN-gateway-rust.md`. Keep it specific to this repository and this
client build. Prefer precise statements over general advice: every claim about the client must
trace to a file in this repository or be marked as an open question.
