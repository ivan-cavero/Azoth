# Prompt: Implement a client-visible server feature

Act as the Azoth server developer for the requested feature. Implement only
the behavior required for the client to reach and maintain the stated state.
Treat protocol and decompilation findings as evidence to re-check, not as
authority. Make the feature understandable and measurable before optimizing
for a future Rust implementation.

## Task input

```text
Feature (for example: world entry, movement sync, combat sync):
Client-visible acceptance criteria:
Client build and relevant atlas/protocol evidence:
Current server state and blocker:
Target load / representative scenario:
Constraints:
```

## Work method

1. Read `AGENTS.md`, `.agents/skills/azoth-server/SKILL.md`, `STATUS.md`,
   `docs/ARCHITECTURE.md`, relevant service docs, and the exact atlas entries.
   Trace the current implementation from transport entry to state mutation
   and outbound response/update before editing.
2. Convert acceptance criteria into client-visible state transitions and
   observable signals. Verify message bytes, fields, ordering, timing, and
   client expectations against the client build and at least one independent
   evidence source. If a key contract is unknown, investigate it first with
   the protocol-analysis prompt; do not fill gaps with guessed protocol code.
3. Implement one supported path with minimal state and clear ownership.
   Separate session/transport, authoritative world state, simulation, and
   outbound replication where the current architecture requires it. Keep
   packet formats and behavior in the protocol/domain layer; do not add
   research controls, guessed fields, or alternate experimental responses to
   the runtime.
4. For movement or physics, specify authority, coordinate/units, tick or
   message cadence, validation, replication fanout, stale-input behavior, and
   disconnect cleanup from evidence. For combat, specify ordering, ownership,
   target/state validation, replication, and duplicate/retry behavior. Make
   only the parts relevant to the assigned feature.
5. Keep a clean path toward Rust: explicit protocol types, bounded work queues
   where needed, owned state transitions, and measurable hot paths. Do not
   build a speculative abstraction or port unrelated code. Python can remain
   the prototype until behavior and load are demonstrated.
6. Define performance claims against a representative scenario. For a 2,500
   or 10,000 player target, identify workload, zone distribution, update rate,
   duration, p50/p95/p99 latency, CPU, memory, queue pressure, and disconnect/
   reconnect behavior. Never infer capacity from a unit test or an idle server.
7. After the behavior works, identify the smallest causal change. Remove
   abandoned branches, flags, one-off scripts, and duplicate implementations;
   retain useful negative findings in the atlas. Update operator and feature
   docs to show one supported way to run and inspect it.

## Deliver

- The implementation and the exact confirmed contract it follows.
- Acceptance signals and evidence; state what was and was not exercised.
- Relevant operational/performance implications and any remaining blocker.
- A concise cleanup report showing which experimental or duplicate paths were
  removed, if any.

Follow root `AGENTS.md`. Do not claim Rust parity or 10k-player capacity until
measured. Do not commit or push, and do not run or add tests unless the user
asks.
