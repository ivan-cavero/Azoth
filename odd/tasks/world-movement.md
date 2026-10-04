# Feature: world-movement (5.1 + 5.4)

Goal: make the possessed local player movable (WASD produces outbound movement
messages / server-driven transform updates) and remove the 30 s
`State(InGame) is timeout` by serving the message the InGame state actually
expects, instead of patching the watchdog.

Decisions (2026-10-02, user):
- Attack movement + timeout together (shared A/B session and server).
- User tests manually (plays, moves camera); orchestrator instruments, reads
  logs, analyzes. No automated SendInput.
- No commits: the user decides when and what to commit.

## Tasks

- [ ] T1 Probe natural spawn (`AZOTH_NATURAL_SPAWN=1`, fresh run, no ladder
  force). Tests hypothesis: forced FSM ladder hides an unmet spawn condition
  that also gates the input controller.
- [ ] T2 Static RE: find the writers of `carrier+0xA0` / `+0xBC8` / `+0x252`
  (the three getters `frida-rep-force-ladder` forces) and the inbound message
  that sets them for real. Outcome feeds `rep.py` protocol fix.
- [ ] T3 Static RE: trace the input -> local controller -> outbound movement
  sender path (0x102e/0x102f et al); identify the gate that fails. Prepare a
  Frida probe for the next fresh run.
- [ ] T4 Timeout: decompile the InGame state descriptor behind
  `FUN_146445E10`; find the expected message; emit it from `rep.py`.
- [x] T5 Two-logger transform A/B (2026-10-03 21:37, pid 23560): retarget both
  warn returns, resolve the real `std::string` at job `+0x110`, attach only
  inside a `remoteplayer` job with `entity+0x60 == 0`, cap 40.
  Result: name resolution and the return-address filter work; 40 attached;
  warnings 26 -> 15; **the client then crashed** (AV `0xc0000005` at module
  offset `0x3F00CE4`) 35 s after the burst, right after
  `OnLocalNetworkConnectionWarning` count 1 and 2. Movement/attack/inventory
  were not testable. Evidence: `azoth-eos-stub.log`, `Game.log` 19:40:16 and
  19:40:51 UTC, WER event 1000. Detail: `symbols.json`
  `gametransform_attach_ab_20261003_2137`.
- [ ] T6 Prove or clear the crash: one fresh exe, stub with the attach OFF
  (the default now; `AZOTH_TRANSFORM_ATTACH=1` re-enables it). If the client
  survives several minutes with the same 26 warnings, the attach caused the
  crash and the component path is closed. Needs `AZOTH_TRANSFORM_ATTACH=1`
  added to `%LOCALAPPDATA%\Temp\azoth-launch-once.ps1` for the other arm.
- [ ] T7 Static RE (the real movement question): who consumes the local WASD
  input, and which message the replay sends *after* login that writes the local
  player's position. Source: corpus + `services/world/replay/messages-redacted.txt`
  + `rep_traffic.jsonl`. Do not synthesise a `0x0008`.
- [ ] T8 Cable: find the real post-login message that rewrites `processor+0x608`.
  `0x15d` and the channel-3 clock do not. Do not hide the icon.
- [ ] T9 Camera lock: explain
  `CameraLockComponentClientFacet: Camera Target Lock Combat Profile is invalid {}`.
  The user is seeing it. Do not hide it.
- [ ] T10 Document each measured A/B in `research/atlas/levers.md` + `STATUS.md`.

## Evidence log

- 2026-10-02 session 232 burst totals: managerSetContext 2, writerStatus1 2,
  insert 226, factory 0, localBuilder 0 — the local player renders as a
  remote-style replica; the known actor-factory path never ran.
- 2026-10-02 live run (PID 19848, world restarted with `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`):
  world rendered, possession lever applied (25 spans), state reproduced 1:1 vs session 232
  (25 RMIDispatch, 26 slice warnings, `State(InGame) is timeout` at +30 s). Confirms the ACK fix
  is correct but does not close the timeout by itself.
- 2026-10-02 RE (corpus + subagent): the component instantiation cluster `0x141761dd0-0x141763df4`
  creates `GameTransformComponent`/`GameRigidBodyComponent` (and facets) BY NAME when container
  byte `[+8]==0`. It has zero code callers — it is entered through a data-table function pointer —
  and the replica portrayal path (`FUN_14178db00` -> delegate invoker / insert) never reaches it.
  The burst-probe `factory: 0` now has a mechanism: the replay only ever populates the portrayal
  table; no real `GameTransformComponent` is ever instantiated. Next probes: live hook
  `0x141761dd0`, data-pointer scan for the table entry, writer of container byte `[+8]`.
- 2026-10-02 late run (21:31Z, PID 5716): full burst captured with early attach. Timeline:
  30x `FUN_141761dd0` (flag=0, CREATE, `GameRigidBodyClientFacetConfig` via `FUN_1416951b0`)
  -> 1589 portrayal delegates -> record1(rec=1) x30 among 283 -> `mgrSetContext` x2 (possession OK).
  `FUN_141763950`/`FUN_141763b70`/spawner `FUN_141582430` = ZERO calls.
- 2026-10-02 mechanism closed: `FUN_141763b70(param_1)` resolves the entity via the VIRTUAL call
  `param_1->vtable[+0x20](param_1, FUN_1407fbe80())` (TLS-indexed per-thread arg). Only when that
  returns non-null does `FUN_141582430` create `GameTransformComponent` (+ attach `m_worldTM`
  `0x140`/`m_parentId`/`m_localTM`). For our player the resolver returns NULL -> no Transform
  component -> not movable, and the same failure explains the 26 remoteplayer slice warnings.
- 2026-10-02 `rep.py::_process_acks` fix REVERTED: reading p[3:5] as an ack of our envelope is
  correct only for the 0x40 continuous form (already covered) and corrupts the 0x8n bitmap forms.
  Regression test added; 63/63 pass.
- 2026-10-02 live decode: at possession the client sends ONE announcement burst byte-matching the
  official capture (0x102e hash 89248843, 0x192c hash 7f789399, 0x12f6 with @cc_* input bindings;
  90x 77B all-distinct bodies) then goes SILENT: WASD produces zero traffic.
  Landmark `client_input_announcement_burst` in symbols.json.
- 2026-10-03 21:37 A/B (pid 23560): the transform hook finally matched the real slice name
  (`slices/remoteplayer.dynamicslice` is a `std::string` at job `+0x110`), attached 40
  components at 21:40:16, cut the warnings from 26 to 15, and the client died at 21:40:51 with
  an access violation. `hits A` 1/26/100/1000 at 21:37:57 / 21:39:32 / 21:40:08 / 21:40:11;
  the second warn return `0x17882D1` never fired, so `FUN_1416797d0` alone writes this run's
  warnings. The attach is now opt-in (`AZOTH_TRANSFORM_ATTACH=1`).

## Commits

(none yet — commits are user-decided)
