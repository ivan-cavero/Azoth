# Prompt: Determine the exact client/server protocol

Act as the protocol investigator for the stated client build and flow. Establish
what the client actually sends, what response it accepts, how often messages
occur, and how those messages change client/server state. Give the server team
a wire-level contract with evidence, not a plausible protocol story.

## Task input

```text
Flow / question (for example: world entry, replication, movement, combat):
Client executable path and full SHA-256:
Relevant Game.log / own gateway / world traces:
Current server implementation:
Unknowns and acceptance criteria:
```

## Work method

1. Read `AGENTS.md`, `.agents/skills/azoth-re/SKILL.md`, relevant protocol and
   world investigation docs, and current atlas entries. Confirm the build
   before applying static addresses or decompilation results.
2. Draw the flow as ordered client/server states and messages. For each
   message, establish direction, transport, host/port, operation or RMI name,
   exact bytes/schema, field casing and order where relevant, required versus
   optional fields, authentication/session identifiers, response/error,
   size, cadence, acknowledgement/retry/timeout behavior, and state side
   effects. Mark unknown dimensions explicitly.
3. Prefer direct observations: Game.log, captures from Azoth's own gateway or
   world server, checked-in fixtures, and repeatable client outcomes. Use xrefs,
   reflection metadata, and decompilation to explain how the client constructs
   or consumes a message, then check important claims against an independent
   signal. Do not infer server expectations from a client-side function name
   alone.
4. Separate labels rigorously: `observed` for captured behavior,
   `statically-derived` for code-path evidence, `validated` for a claim
   confirmed by independent observation, and `guessed` for a hypothesis.
   Include the full client SHA-256 and exact evidence location/range for every
   fact. Preserve contradictory evidence instead of silently choosing one.
5. For replication, distinguish transport/session setup, entity identity and
   ownership, component creation, initial state, ongoing updates, relevance
   or interest, movement/physics authority, acknowledgements, and teardown.
   Prove the transition needed for the next client state. Do not declare a
   world feature understood just because the client connected or displayed a
   player identity.
6. Update the canonical registry in `research/atlas/` (endpoints, models,
   errors, observed endpoint families, or client functions as appropriate).
   Mark unconfirmed fields as guessed. Store sensitive/raw payloads and local
   captures only in ignored `research/sessions/`; put a redacted fixture in
   the repository only when it is safe and necessary to reproduce the fact.
7. Stop investigating once the acceptance question has a minimal, independently
   checked answer. Record useful negative results. Do not leave every probe,
   candidate schema, and failed response path as production behavior.

## Deliver

- A concise state diagram or ordered message table from initial connection to
  the requested stable state.
- Exact confirmed request/response contracts, timing/retry facts, and evidence
  references, plus a separate list of hypotheses and missing proof.
- A short server handoff: minimum accepted behavior, the next unmet transition,
  and a reproducible verification signal.
- Updated atlas records and focused docs without duplicating the registry.

Follow root `AGENTS.md`. Capture only traffic to Azoth's own services; never
attempt MITM against Amazon endpoints. Do not commit or push, and do not run or
add tests unless the user asks.
