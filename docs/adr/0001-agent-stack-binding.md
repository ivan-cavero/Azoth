# 0001. Agent stack binding

Date: 2026-10-24
Status: accepted

## Context

Azoth is built primarily with AI agents. The operator typically runs two
concurrent slots, DeepSeek-v4.1-flash through the Pi harness, Gentle AI for
Organic Driven Development, and Orca or T3 as the outer orchestrator. Long
STATUS novels and unbounded chat sessions collapse overnight work.

## Decision

- **Outer shell:** Orca (Run/Task/Dispatch/worktrees) or T3 orchestrator MCP —
  one active choice per night, not both fighting for the same workers.
- **Workers:** Pi + Gentle AI + DeepSeek-v4.1-flash on isolated git worktrees.
- **Concurrency:** at most one writer per worktree; with two slots prefer
  orchestrator+worker or implement+verify on disjoint trees.
- **Promotion:** LLM/output never writes `confidence: verified` or public
  roadmap `done` without a verifier node or human gate.
- Details: `docs/PLAN-master-platform.md` §12 and §14A.

## Consequences

- Overnight recipes must use heartbeats, `worker_done`, and checkpoints.
- Nested `AGENTS.md` and ontology become the context diet; not full STATUS.
- Stronger models may be handed a single high-risk task via T3/Orca; bulk
  ontology/decomp stays on flash.

## Alternatives considered

- Pure LangGraph in-repo runner first — deferred; reuse Orca/T3/Pi durability.
- Unlimited parallel writers — rejected; two-slot budget and writer locks.
