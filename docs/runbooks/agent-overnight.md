# Overnight agent loop (Orca + Pi + Gentle + DeepSeek)

Binding: [`docs/adr/0001-agent-stack-binding.md`](../adr/0001-agent-stack-binding.md)
and `docs/PLAN-master-platform.md` §14A.

## Preconditions

- Experimental Orca orchestration enabled (or T3 orchestrator equivalent).
- Clean worktree budget: one writer per tree.
- Root `STATUS.md` is the frontier only; load atlas/ontology uids for the gate.
- Max two concurrent agent slots.

## Recipe (Orca-shaped)

```text
1. orca orchestration run-create --objective "Azoth: <gate-id>" --json
2. Create DAG tasks: explore | implement | verify (verify never same author tree)
3. worker-start --task <id> --worktree new-child --agent pi --json
4. Worker preamble must include:
   - path to AGENTS.md (root + nearest nested)
   - gate acceptance criteria
   - ontology concept uids in scope
   - "send heartbeat; one worker_done; ask() for product decisions"
5. Orchestrator: check --wait for worker_done|escalation|question
6. On succeeded + promote needed → decision gate for human (morning)
7. Do not leave completed worker terminals open; worker-release after read
```

## Gentle rules inside the worker

- Delegate only for exploration, parallel disjoint writers, context backstop,
  or independent verification.
- Small understood work stays inline.
- High-risk (wire, privacy, economy, auth) → separate verify worker.

## Morning triage

1. Read orchestrator inbox / dashboard thread.
2. Resolve decision gates (atlas promote, roadmap public `done`).
3. **Pre-public:** push the working branch when the user wants sync (`git push`);
   no PR theater until plan P22. After public open: PR + required checks.
4. Update root `STATUS.md` frontier in ≤ a few bullets; diary → `docs/journal/`.
