# Prompt: Azoth code and repository refactoring

Act as the maintainer responsible for making the requested Azoth area easier
to understand, change, and operate. The goal is to keep confirmed behavior
while removing accidental complexity, stale alternatives, and unclear
ownership.

## Task input

```text
Goal:
Scope / paths:
Known behavior that must stay compatible:
Pain points:
Constraints / acceptance criteria:
```

## Work method

1. Read `AGENTS.md`, `STATUS.md`, and the architecture or service docs for the
   affected area. Inspect the actual callers, entry points, configuration,
   generated files, and scripts before changing layout or APIs.
2. Establish which behavior is supported by current evidence and which code
   is only a historical experiment. Check references before removing a script,
   document, or tool; update its callers and index in the same change.
3. Choose one clear owner and one normal path for each responsibility. Remove
   duplicated implementations, dead options, compatibility layers without a
   current caller, excessive wrappers, and comments that merely repeat code.
4. Keep service/runtime code limited to behavior the game or operator needs.
   Keep reverse-engineering, capture, corpus generation, and experiments in
   the research/tooling area. Do not add research-only fields or controls to
   the production protocol.
5. Preserve wire details exactly when they are confirmed. Before changing a
   protocol path, consult its atlas entry and verify the client-visible
   behavior; never "clean up" casing, ordering, errors, or timing based only
   on style preference.
6. Prefer readable standard-library Python and focused modules. Add an
   abstraction only when it removes real duplication or gives a measured
   performance/ownership benefit. Optimize measured hot paths; avoid
   speculative tuning and generic frameworks.
7. Update docs and command indexes to describe the one supported workflow.
   Remove obsolete notes and failed alternatives instead of accumulating
   another layer of explanation.

## Deliver

- Implement the scoped refactor, keeping unrelated changes untouched.
- Summarize the prior complexity, the new ownership/path, and why the result is
  simpler without changing supported behavior.
- List important removals and any migration or compatibility impact.
- Report the validation actually performed; do not claim tests or runtime
  behavior were verified if they were not.
- Leave a short list of genuinely unresolved questions only when evidence is
  insufficient to settle them.

Follow root `AGENTS.md`. Do not commit or push, and do not run or add tests
unless the user asks.
