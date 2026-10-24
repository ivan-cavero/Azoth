# Azoth agent prompts

These prompts define reusable workflows for work in this repository. Paste
the autonomous driver into a fresh session without filling in a task field; it
uses the user's current request. For a focused role prompt, fill in its `Task
input` fields. A prompt does not replace the repository rules or authorize
actions that the task did not request.

## Choose a role

| Prompt | Use it for | Main output |
| --- | --- | --- |
| [Azoth session driver](autonomous-driver.md) | Any Azoth task in any session; selects the matching focused prompt/skill, coordinates up to two useful subagents, and drives work to verified acceptance | An Azoth-specific result with canonical documentation, authentic roadmap evidence, and a concise handoff |
| [Code refactoring](refactor.md) | Simplifying or reorganizing existing implementation and docs | A smaller, clearer design that preserves confirmed behavior |
| [Full project audit](project-audit.md) | A whole-repo merge-readiness review (self-containment, broken references, suites, evidence) | A verdict with severity-grouped findings and unambiguous fixes applied |
| [Decompilation review](decompilation-review.md) | Building, auditing, naming, or organizing a build-specific decompilation | A hash-scoped corpus with coverage, evidence, confidence, and unresolved gaps |
| [Protocol analysis](protocol-analysis.md) | Establishing exact client/server messages and state transitions | Atlas-backed wire facts and a traceable flow description |
| [Server feature development](server-developer.md) | Implementing a client-visible feature such as world entry, movement, or combat | A minimal server behavior with protocol-backed acceptance criteria |
| [Live client analysis](live-analysis.md) | A specifically requested experiment using a private client process, memory, or hooks | A reproducible, time-correlated trace and independently checked finding |
| [Boot naming campaign](boot-naming-campaign.md) | Name every critical-path surface from process open → InGame into ontology | Ontology + atlas coverage toward the campaign gate |

Use the autonomous driver as the session-level prompt. It selects one focused
role prompt below when the task calls for it; do not stack role prompts that
cover the same work.

For a world feature whose protocol is unknown, use **Protocol analysis** to
establish the message contract, then **Decompilation review** for unresolved
client-side code, and **Live client analysis** only if static evidence and
existing captures cannot answer the question and live analysis is allowed.
Pass the evidence to **Server feature development**. Use **Code refactoring**
to simplify the resulting implementation and remove obsolete experiment paths.

## Shared rules

- Read the root `AGENTS.md`, current `STATUS.md`, and the relevant focused docs
  or skills before acting. Follow the live-debug and reverse-engineering rules
  when applicable.
- Verify important prior findings. Decompiled pseudocode, names, comments,
  old notes, and a previous agent's conclusion are leads, not proof.
- Label each claim as observed, statically derived, independently validated,
  or guessed. Attach the client SHA-256, file offset/VA, packet/fixture, log
  range, or other evidence needed to reproduce it.
- Keep raw captures, client files, generated decompilation projects, secrets,
  and machine-specific paths in the existing ignored locations. Put durable
  protocol facts in `research/atlas/` and link to that source instead of
  copying facts into multiple documents.
- Prefer the smallest change that explains the confirmed behavior. Do not
  preserve failed experiments as runtime alternatives. Record useful negative
  results, then remove temporary branches and update the tool index.
- Do not commit or push. Do not run or add tests unless the user asks.

## Task input

When useful, include these fields after the selected prompt:

```text
Goal:
Scope / paths:
Known client build (full SHA-256 if available):
Known evidence and uncertainties:
Constraints / acceptance criteria:
```
