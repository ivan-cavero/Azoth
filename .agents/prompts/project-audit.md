> This prompt is not the driver. Read `STATUS.md` and `.agents/skills/everfall-next/SKILL.md`. The Rust tree `server/` was deleted. Do not recreate it from these steps.

# Prompt: Full project audit (merge readiness)

Act as the Azoth project auditor. Perform one full top-to-bottom review of the
repository and produce a verdict on whether the project is coherent, self
contained, and ready to merge. This runs once when the project starts (after a
large refactor) and can rerun before important merges.

## Task input

```text
Merge target / branch under review:
Scope exceptions (paths known to be in flight):
Known risks from the last session:
```

## Work method

1. Read `AGENTS.md`, `README.md`, `STATUS.md`, and `docs/ARCHITECTURE.md`
   first. Everything else is reviewed against the structure they describe.
2. **Self-containment.** Verify the repo does not depend on AppData, machine
   paths, or out-of-repo state to build, test, or run: search for `AppData`,
   `%LOCALAPPDATA%`, `C:\Users`, and hardcoded absolute paths. The only
   allowed references are: documented Windows shell variables for official
   client data (`Game.log`), the one-time `python ef.py migrate`, and the
   launcher redirecting env vars into `private-client/`.
3. **Broken references.** Extract every path mentioned in docs, scripts, and
   JSON, and verify the target exists. Pay special attention to tools deleted
   in the last refactor: a doc that cites a removed script either gets its
   pointer updated or the script comes back. Bare filenames used as shorthand
   are acceptable only when unambiguous within the doc.
4. **Entry-point coherence.** `python ef.py` is the only command. It covers
   setup, migrate, dev, game, status, re, probe, run, and doc. No second
   supervisor (`az.py`, `az.ps1`, or another launcher at the repo root) may exist.
5. **Test readiness.** Run the existing unittest suites
   (`services/gateway/tests`, `services/world/tests`) and any others reachable
   through the documented commands. Every suite must pass without manual
   setup; a test that depends on untracked or generated files is a finding,
   and its fixture either becomes tracked (if redacted and needed) or the
   test gains a skip with a reason.
6. **Evidence integrity.** Spot-check that atlas entries carry evidence labels
   and build hashes, that confirmed facts live in `research/atlas/` (not
   copied into chat-only docs), and that `STATUS.md` matches reality.
7. **Function-area sense check.** For each area — gateway, world, launcher,
   reverse tooling, campaign, client map, prompts, skills — verify the docs
   describe the code as it is, one supported path per responsibility, and no
   duplicated or dead alternative paths.
8. **Git hygiene.** Confirm ignored locations (`private-client/`, `.azoth/`,
   `reverse/builds/`, raw captures, screenshots) are not staged; confirm no
   secrets or raw payloads in tracked files. Do not commit or push.

## Deliver

- A verdict: merge-ready, or merge-ready after the listed fixes.
- Findings grouped by severity: blocking (broken path, failing suite, secret,
  missing tracked fixture), major (stale doc, wrong pointer, duplicate path),
  minor (style, wording). Each with file:line and the exact fix.
- Fixes applied for blocking/major findings when they are unambiguous; ask
  before any structural or behavioral change.
- A one-line health statement per area and an updated `STATUS.md` if the
  project frontier changed during the audit.

Follow root `AGENTS.md`. Do not commit, push, or run live-game experiments.
