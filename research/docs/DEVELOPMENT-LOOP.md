# Azoth development loop

Azoth will keep growing after the first world loads. Multiplayer, movement,
combat, mobs, NPCs, quests, persistence, and UI flows can each fail at a
different boundary. This workflow makes each failure quick to reproduce,
diagnose, fix, and keep fixed.

## One case, one traceable chain

Every issue follows this chain:

1. **Name the observable failure.** Describe what the user sees and what the
   client/server logs show. Avoid labels like “spawn is broken” until the
   failing layer is known.
2. **Write a minimal reproduction.** Record build, mode, starting state,
   characters/players, steps, and expected vs actual result. Make it repeatable
   without relying on memory or an old process.
3. **Collect evidence on both sides.** Save the smallest useful client-log,
   server-log, and packet/traffic ranges with timestamps. For network behavior,
   compare what the client sent, what the server received, what it replied, and
   what the client acknowledged or acted on.
4. **Draw the path.** Identify the path through client → transport → wire decode
   → dispatch → model/state → game behavior. Mark the first boundary where
   expected evidence disappears.
5. **State one falsifiable hypothesis.** Predict an observation that would
   distinguish it from the next likely cause. Change one variable per live A/B.
6. **Choose the cheapest test that can decide it.** Prefer a unit test or saved
   fixture; then a service/contract test; then a fresh-process game attempt.
   Never spend a two-minute game restart to answer something a static decode or
   unit test can settle.
7. **Fix the narrowest layer that owns the failure.** Add the smallest
   regression check that would have failed before the fix.
8. **Record the result where future work starts.** Update the source of truth
   below, summarize the current frontier in STATUS.md, and add a dated case
   entry. Keep dead hypotheses marked closed with evidence so they are not
   repeated.

## Evidence standard

Use these labels consistently in notes and artifacts:

| Label | Meaning | Example |
| --- | --- | --- |
| **Observed** | Direct output from this build/run; include file, timestamp, and range. | Game.log contains the 26-message drain at 14:03:12. |
| **Derived** | Follows from reproducible parsing or static analysis; include tool, build, and VA/offset. | decomp.py shows the branch calls Cleanup() when the flag is zero. |
| **Validated** | A controlled test confirms the prediction; include setup and result. | On a fresh process, suppressing the duplicate LevelInfo preserves the context. |
| **Inferred** | Plausible explanation not yet isolated by a deciding test. | Seq 0x25 is the current leading HOL-block hypothesis. |
| **Guessed** | Unverified schema or interpretation; label it explicitly. | evidence=guessed in atlas data. |
| **Closed** | Tested and rejected, or superseded; link the deciding evidence. | Reliable heartbeat conclusion superseded by 2026-09-30 measured exchange. |

Never upgrade an inference to a fact because it sounds likely. Preserve
negative results with the exact build, clean-process condition, and the signal
that proves the experiment actually ran.

## Where each artifact belongs

| Artifact | Location | Purpose |
| --- | --- | --- |
| Current project frontier | ../../STATUS.md | Short dashboard and links; keep it lean. |
| Protocol/schema fact | ../atlas/ | Endpoints, exact models, errors, levers, observed traffic. This is the source of truth for RE facts. |
| Function/address fact | ../derived/symbols.json | Confirmed symbol, VA, meaning, method. Other derived/ files are regenerable. |
| Minimal input/output fixture | ../fixtures/ | Stable bytes or JSON used for repeatable parser/contract tests. Keep provenance and redaction notes beside it. |
| Automated regression | services/<service>/tests/ | Fast offline checks for wire parsing, dispatch, and service behavior. Use stdlib unittest per repo rules. |
| Live run raw material | ../sessions/ | Gitignored captures and logs. Keep only necessary excerpts or derived evidence tracked. |
| Investigation narrative | research/docs/ | Dated hypotheses, measurements, and next frontier by subsystem. |
| User-facing project history | docs/sessions/ | Historical sessions only; leave Spanish archives unchanged. |
| Tool usage | scripts/README.md, tool README files | Discoverable index; do not relocate invoked scripts without updating every caller. |

Traffic and binary captures can contain identities or machine-specific paths.
Keep raw sessions ignored, redact exported fixtures, and retain only the bytes
needed to reproduce a finding.

## Test ladder

Run the lowest layer that answers the question, then move upward only when
needed:

1. **Static analysis:** strings/xrefs/disassembly/decompilation for code paths,
   property registries, and call relationships. Cache Ghidra and use the
   persistent decompilation server for a batch of targets.
2. **Pure unit test:** encode/decode round trips, boundary lengths, ordering,
   state transitions, and malformed inputs. These should run without a game.
3. **Fixture/contract test:** replay a saved message or request through the
   parser/dispatcher and assert the exact model and resulting state changes.
4. **Service integration:** exercise DTLS/Carrier/REP or gateway behavior with
   local services, raw logs, and a known fixture.
5. **Live client A/B:** use one clean game process per variant, record all
   settings, and verify a progress marker before interpreting any hook/counter.
6. **End-to-end scenario:** verify the complete user-visible behavior and
   retain the scenario as a reusable checklist or harness.

Tests added for a defect should run before the change is considered done. The
repository-specific commands and authorization to run them are governed by
AGENTS.md.

## Build a progression, not a pile of patches

For each feature, track the same checkpoints independently:

| Checkpoint | Evidence of completion |
| --- | --- |
| Transport | Connection/handshake and keepalive are stable; disconnect reason is visible. |
| Wire | Captured or derived message shape round-trips and is version/build scoped. |
| Dispatch | Correct handler/facet receives the message; unknown targets/types are logged with enough context. |
| State | State changes are explicit and testable; entity/character identity is consistent. |
| Behavior | Client acts on the state: possession, movement, combat, NPC interaction, quest progress. |
| Two-client behavior | Both clients observe the same authoritative state and ordering; reconnect/late join has a defined result. |
| Regression | The scenario can be replayed offline or with a documented short live run. |

Do not mark a feature “working” at an earlier checkpoint if the user-visible
behavior is still absent. For example, a successful DTLS handshake is not a
working world; a decoded spawn message is not a possessed player.

Use these milestone slices to organize the next work after world entry:

1. One player is spawned, possessed, and can move.
2. Two players can join; the server keeps distinct identities and both clients
   see consistent spawn/despawn and movement updates.
3. Combat and one simple mob work as an authoritative state change visible to
   both clients.
4. One NPC interaction updates a minimal quest objective, with state surviving
   reconnect if persistence is in scope.
5. Reconnect, late join, and server restart behavior are defined and replayable.

Each slice gets its own reproduction and acceptance evidence. This keeps a
later quest or synchronization bug from being confused with an earlier
transport or entity-creation failure.

## Case note template

Copy this into the subsystem investigation doc for a new issue. Keep raw logs in
the ignored session area and cite only the necessary excerpts here.

```text
Date/build:
Observed failure:
Minimal reproduction:
Expected / actual:
Evidence files and timestamp ranges:
Path under investigation:
Hypothesis (observed / derived / inferred / guessed):
Cheapest deciding test:
One changed variable:
Result (validated / rejected / inconclusive):
Regression added:
Atlas/symbols/docs updated:
Next frontier:
```

## First current case

The black-screen case and its current measurable frontier are in
WORLD-DEBUGGING.md. Treat it as the first case on this workflow: the transport
and initial state drain are proven, but the application dispatch has missing facet targets
and the local-player holder remains null. Carrier ACKs do not prove bundle application or possession.
