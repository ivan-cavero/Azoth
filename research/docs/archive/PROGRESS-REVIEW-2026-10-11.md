# Four-day progress review - 2026-10-11

## Scope and conclusion

This review covers the 13 commits dated 2026-10-08 through 2026-10-11 and the evidence available in the current checkout. The user-visible objective is a usable in-world session with a healthy connection indicator and controllable movement.

The project did make substantial progress in protocol decoding, server-loop reliability, client probes, registries, and the run workflow. It did **not** close either visible acceptance gate: the ALC/HUD cable remains red and W does not move the player. Possession and REP transport uptime are real milestones, but they were repeatedly allowed to stand in for connection health or movement. That made the roadmap and screenshots look further along than the game was.

## What changed in the last four days

| Date / commit | Work recorded | User-visible result |
| --- | --- | --- |
| Oct 8 - `4b03eb4` | Server contract and session details | Documented the entry/possession slice; no movement or visible-connection pass |
| Oct 10 - `b5b56dd` | Authoritative server tick; reduced UDP-loop stalls, ACK amplification, and heartbeat retries | Meaningful transport/server reliability work; not an ALC/HUD fix |
| Oct 10 - `48154d8` | Prefix-varint and StateBundle parsing | Protocol/container knowledge improved; no movement pass |
| Oct 10 - `fb200c6` | PowerShell 5.1 launcher fix | Restored the documented launch path |
| Oct 10 - `0eddd30` | Persistent decompilation campaign manifest | Improved research continuity |
| Oct 10 - `069cfe4` | Message, AZ type, and AOI trait registries | Large generated/reference-data change (32,858 insertions); not a shipped gameplay feature |
| Oct 10 - `dc4bf98` | State-bundle and movement Frida probes | Better measurement tools; no movement pass |
| Oct 10 - `4fd3e71` | Protocol/evidence corrections | Useful durable protocol findings |
| Oct 10 - `a53e6a7` | Fresh-session handoff | Better onboarding, but some handoff claims still needed reconciliation |
| Oct 10 - `ee507a6` | Scanner fail-safe behavior | Better tooling safety |
| Oct 10 - `f8f3d08` | Reframed objective and ranked experiments | Better sequencing, but later measurements still needed to supersede early conclusions |
| Oct 11 - `49ef58f` | Bilingual live-roadmap site and deployment | 12,143 insertions; presentation work while the gameplay gates remained open |
| Oct 11 - `3dd36e7` | Roadmap/Gantt detail modals | 1,095 more insertions; improved UI, not game progress |

Raw insertion counts are not a progress score: generated registries dominate the total, and the two site commits account for about 13.2k insertions. The key distinction is **research/tooling progress versus a verified player-facing result**.

## Why it felt like no progress

1. **Acceptance criteria were too weak.** `transportError = 0` was treated as connection stability even when the user's real HUD cable was red. A screenshot difference was treated as movement even though the player's transform was never measured.
2. **A false movement positive escaped.** The old BMP motion ratio was interpreted backwards for coherent translation. The “player walks” claim is retracted; movement requires a direct transform delta and input/release correlation.
3. **An incorrect component diagnosis sent work down the wrong branch.** A shifted GUID list said the player had no physics. The corrected live 126-component entity has `CharacterPhysicsComponent` and `GameRigidBodyComponent`. Their presence does not prove active simulation, but generic `PhysicsTrait` replication is not justified as the fix.
4. **Protocol milestones were overstated.** Reliable flags `0x21` make wire 4216 reach its reader 212 times; they do not apply a position. RMI dispatch then fails 103 times because the target facet is missing. Likewise, accepted type/framing and input-response messages do not open the ALC door.
5. **Three different connection signals were merged.** REP transport, `OnLocalNetworkConnectionWarning` in `Game.log`, and the red ALC/HUD icon are separate observations. The icon follows the last-response stamp: amber at 2 s and red at 15 s. Later live probes found `+0xAA0` closed and the HUD stamp stopped advancing even while REP stayed alive.
6. **Historical experiments became current prescriptions.** The `0x1b88` stream once coincided with a 40-minute session, but that session disconnected and did not prove a stable user-visible connection. A 20 ms chunk gap passed one old run but later A/Bs showed it is slow and close to the watchdog; the default 4 ms is the baseline, not a universal fix.
7. **The public roadmap was not an evidence view.** It showed unsupported completion language/ETA and reused the same poor `world-possessed` image across unrelated steps. A world-possession picture proves a rendered scene, not physics, movement, or connection health.
8. **Documentation drift caused rediscovery.** A handoff could say the tree was clean or a gate was solved while current evidence was contradictory. Findings and failed hypotheses were not always carried to their canonical atlas, status, runbook, and public roadmap locations.

The main failure was not lack of activity. It was converting measurements from one layer into claims about another, then leaving those claims visible after later evidence had overturned them.

## Current measured state

- World entry, rendering, and possession reproduce.
- REP transport survived a measured 2 h 06 min run without a transport error or REP disconnect. The red ALC/HUD warning remained visible, so visible connection health is **not solved**.
- The ALC door at `+0xAA0` stayed closed in the measured probe; the HUD `+0xAA8` stamp stopped advancing. Input-response messages and `StartMovementCommunicationMsg` did not open the door. The exact handshake producer is unknown.
- The player entity has physics component types, but active body/controller state and the reason W does not move are unknown. W produced no movement-family message in the sampled run; measure the transform directly and trace channel-1 `0x635`.
- Reliable 4216 reaches the reader and then fails facet-target dispatch. No position change is established.
- The client still has a separate approximately 20-minute return-to-menu path. Patching `0x141004230` did not stop it.

Canonical evidence: [`STATUS.md`](../../STATUS.md), [`HANDOFF.md`](../../HANDOFF.md), [`client-functions.json`](../atlas/client-functions.json), and [`docs/ROADMAP.md`](../../docs/ROADMAP.md).

## Plan to achieve connection health and movement

### Gate 0 - one trustworthy baseline

On a fresh client process, capture the build SHA-256, config, exact run ID, real HUD color, REP logs, `+0xAA0`/`+0xAA8`, player transform, body/controller state, and channel-1 `0x635` counters. Attach before world entry. Hold W, release it, and include an idle control. Change one variable per run. Do not use screenshot-diff ratios as pass/fail.

### Gate 1 - open the real ALC conversation

Trace the producer/consumer path for the closed ALC pointer and stale response stamp. Distinguish direct observation from the current server-handshake inference. Do not repeat already negative levers as fixes: input-response replay, `StartMovementCommunicationMsg`, and position replies did not open `+0xAA0` in measured runs. Implement only a message/behavior whose client call path and server contract are evidenced.

**Pass:** the actual HUD warning disappears/returns to its normal state; `+0xAA0` opens and the expected response stamp advances through the protocol; REP shows no transport error/disconnect; the client remains in-world beyond the known 20-minute point. First observe 30 minutes, then perform a 2-hour soak.

### Gate 2 - identify the local movement path

With the same early probe, correlate W-down/W-up with the local transform, body/controller activation, the consumer of `0x635`, and ALC state. Physics component presence alone is not activation proof. The old `FUN_141763b70` observation is a lead, not the cause. Avoid generic fragment scans unless the live path shows a particular fragment is required.

### Gate 3 - make position application valid

Trace the missing `IPositionReceiver`/facet binding for reliable 4216. The reader count is a decode signal only. Fix target creation/binding from evidence, then verify a logged dispatch and an applied transform change.

### Gate 4 - movement acceptance

Require the transform to move in the expected direction while W is held, stop after release, and correlate with a successful client/server movement exchange. Then verify turning, collision, and server-authoritative validation. Record negative attempts and side effects. Only after these pass should later content or capacity work depend on movement.

No finish date is credible until the ALC and movement call paths are identified.

## Roadmap and visual corrections made in this review

- Split transport uptime from the visible ALC/HUD gate and the 20-minute return-to-menu path.
- Replaced the stale PhysicsTrait-first plan with transform/body/controller/input measurements and the 4216 facet-target blocker.
- Removed unsupported ETAs and old claims that transport uptime or decoder success meant the goal was done.
- Removed both tracked public JPEGs (`game-shot.jpg` and `research-shots/world-possessed.jpg`) and all site references to the repeated possession screenshot. Do not add a screenshot to a roadmap item unless it is a genuine capture of that specific acceptance result.
- Added a handoff rule in `AGENTS.md`: every contributor records artifacts, exact build/run evidence, observed versus inferred claims, validation, failed hypotheses, side effects, and the next blocker. The coordinator checks and reconciles it before calling work complete.

## Validation and publication

This review did not launch the game or run test suites. Static checks verified the public-roadmap JSON and atlas JSON parse, and `git -c core.whitespace=cr-at-eol diff --check` passed. The current tree has uncommitted and untracked work; nothing was committed or pushed. The site source changes are local and have not been built or published, so the hosted page will remain unchanged until the project owner chooses to publish.
