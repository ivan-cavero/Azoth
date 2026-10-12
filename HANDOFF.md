# Handoff — Azoth (New World private server)

Session handoff for a fresh agent with zero context. Read `AGENTS.md`,
`STATUS.md` and this file first, then the two protocol references it points at.

Working directory: the repository root. Branch `main`.

## Hard rules

- **Do not commit or push unless the user explicitly asks.** At the time of
  writing, everything below IS committed (see "Repository state"), but the rule
  stands for new work.
- **Steam is read-only.** Never delete, move, modify or hardlink anything under
  the Steam install. Losing `assets/*.pak` (~76 GB) once cost a full
  re-download. The private client is a COPY at
  `private-client/runtime/Bin64/NewWorld.exe`; patches apply to that copy only,
  and `python scripts/patch-dtls-disk.py restore` puts it back byte-identical.
- Do not run tests unless needed to validate a change; the suites are fast
  (`python az.py world test`, `python az.py gateway test`).
- Keep raw captures, client files, generated decompilation and secrets in the
  ignored locations. Durable facts go in `research/atlas/`, not in chat.
- Docs and code are in English. `docs/sessions/` history stays in Spanish.

## Repository state

- At the 2026-10-11 review snapshot, branch `main` was aligned with
  `origin/main`, but the worktree had local edits and untracked probes/reports.
  Inspect `git status --short` before starting; do not assume those findings are
  committed or shared.
- Build in scope: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`
  (Steam `Bin64/NewWorld.exe`, 179,204,176 B, `[RETAIL].Javelin.1.400.6031.6004151`).
- Most recently documented: **120 world**, **24 gateway** tests passed. This is
  a recorded result, not a claim that the current uncommitted tree was retested.
- Decompilation corpus: 423,579 `.pdata` ranges, **423,542 ok / 37 fail**
  (20 timeouts, 10 mid-function varnode fragments, 6 payload-cap, 1
  address-space). It does **not** cover 13,943 leaf functions in `.text` that
  carry no unwind info — reach those with `decomp.py --range`, not `--target`.
- Campaign manifest: **50 targets** (`research/atlas/decomp-campaign.json`).
- Toolchain: `.\az.ps1 setup` installs checksum-verified CPython, Ghidra 12.1.4
  and JDK into ignored `.azoth/`. On an existing machine run
  `python az.py migrate` once, after closing NewWorld.

### On a fresh machine

Ignored and therefore NOT in git: `.azoth/` (toolchain, venv, logs),
`private-client/` (game copy, profile, runtime), `reverse/builds/` (corpus,
Ghidra project), `research/sessions/`, `services/gateway/traffic.jsonl`.
After cloning: run `.\az.ps1 setup`, then `python az.py migrate` if migrating an
old per-user state, then rebuild the corpus with
`python az.py re corpus` if you need decompilation. Everything committed is
self-contained: code, docs, and the atlas registries.

## What travels with git, and what does not

Working on two machines is fine, but only if you know which side of this line
each thing is on. `git ls-files` is 333 files: all code, docs, tests, the atlas
registries, the probes and the scanners. Everything else is ignored,
deliberately, and falls into three groups.

**Regenerable from the committed lock plus the Steam install.**

| what | how to regenerate | cost |
| --- | --- | --- |
| `.azoth/` toolchain (~3.9 GB) | `.\az.ps1 setup`, pinned by the committed `toolchain.lock.json` | a large download, but deterministic |
| `private-client/runtime/` (269 MB) | the launcher rebuilds it from the Steam install; `assets` is a junction, not a copy. **This is where `typeindex.json` comes from**, which `reverse/tools/scan-*.py` need | launch the client once (`python az.py game`) |
| `private-client/profile/` (43 MB) | game local settings | automatic |
| `services/world/certs/` | regenerated on demand if absent | free |
| `.codegraph/` (7 MB) | rebuild the index | minutes |

**Expensive to regenerate, so decide deliberately.**

`reverse/builds/<sha256>/` is 1.6 GB and it is the one that actually hurts:

| part | size | notes |
| --- | --- | --- |
| `corpus/` | 1.2 GB | decompiled pseudocode for all 423,579 `.pdata` functions. Rebuild with `python az.py re corpus`; **it is resumable**, so an interrupted run is not lost |
| `ghproj/` | 459 MB | the analyzed Ghidra project; re-importing the exe and re-analyzing is the slowest step |
| `xrefmap.json` | 12 MB | rebuilt in minutes |
| `campaign/` | 2.2 MB | this project's own campaign output |
| `functions/` | **106 KB** | the specific decompiles done for this project |

If you want to move work between machines, the cheap high-value subset is
`functions/` plus `campaign/` plus `campaign-state.json` plus `xrefmap.json` —
about **14 MB**, and it carries every specific decompile the project has done.
The 1.2 GB corpus is bulk pseudocode that only a full-text search needs; rebuild
it on demand rather than copying it.

**Not regenerable, and not recoverable either.** Session evidence under
`research/sessions/` (427 MB) records observations of specific runs: `Game.log`,
screenshots, ACK dumps, raw gateway payloads. Repo rules say raw captures stay
out of git, so a measurement made on one machine is not visible from the other.
If a conclusion matters it has to be written into the atlas with its `found_by`
— which is what the atlas entries do — rather than left implicit in a capture
file.

**Nothing else needs committing.** Every derived artifact from this session is
tracked: `javelin/varint.py`, `javelin/bundle.py` and their tests, the three
scanners, the three generated registries, the six probes, and the docs. The only
ignored artifact that is small and load-bearing is `typeindex.json`, and that one
is better rebuilt from the install than committed, because it is a game file.

### Two traps this audit found

- `services/world/rep_traffic.jsonl` is **2.4 GB** of append-only traffic log. It
  is a debugging log, not state; delete it rather than carrying it, and remember
  it accumulates across sessions.
- `scan-az-types.py` used to degrade **silently** when `typeindex.json` was
  missing, writing a registry with every `in_type_table: false`. It now refuses
  to write. Both scanners previously told you to run `python az.py disk`, which is
  not a command that exists; they now name the launcher instead.
## What is confirmed (do not repeat the old diagnosis)

1. **World entry and possession reproduce.** The private client renders the
   world and possesses the player. The red ALC/HUD warning remains visible.
2. **REP transport survived one 2 h 06 min run** with `transportError` 0 and
   `disconnected from REP` 0. This is transport uptime, not user-visible
   connection success: the ALC door remains closed, its input stamp stops, and
   a separate ~20-minute return-to-menu path remains open.
3. **The protocol container, decoded.** The prefix varint, the byte-exact
   type-0x08 state bundle, the record sequence, and the two-varint fragment
   header. `services/world/src/azoth_world/javelin/varint.py` and `bundle.py`,
   with tests. The server can now READ and BUILD a bundle, not just replay one.
4. **The message/type/trait registries.** 144 Javelin messages with wire types,
   4814 AZ types, 82 AOI traits with 2276 pairs. Three self-verifying scanners
   under `reverse/tools/`.

## What is OPEN — and the reframe that matters

### Latest measured results (2026-10-12, live + static)

- **The live player entity's 126 components are dumped and named.** The old probes rejected
  126/126 components by checking `inCode(vtable)`; on this build the vtable is in `.rdata` and
  the function pointer inside it in `.text`, so check the FUNCTION POINTER. Fixed, run
  `comp-083309` resolved 126/126 with zero failures. Probe
  `reverse/probes/client/frida-player-components-full.py`. Atlas:
  `player_entity_component_list_measured_20261012`.
- **`PlayerPositionTrackingComponent` IS on the entity** (index 95, GUID `62620B33-…`), along
  with `CharacterComponent`, `Transform`, `TraversalComponent`, `CameraLockComponent`,
  `PlayerInputFiltersComponent`, `MotionParameterSmoothingComponent`, `PlayerAOIComponent`,
  `SpectatedPlayerComponent`, `SpectatorModeComponent` and more.
- **`CharacterPhysicsComponent` / `GameRigidBodyComponent` do NOT reproduce on the live
  entity** (~4 s after spawn), by the component-list dump AND by asking the client's own
  lookup (both byte orders, controls positive). This is an UNRESOLVED disagreement with
  `local_player_components_step0_20261010`, not a retraction; the deciding experiment is to
  re-dump at spawn+4 s / +30 s / +2 min while logging every ADD (`FUN_1413789c0`). Atlas:
  `physics_components_absent_on_the_live_player_entity_20261012`.
- **Frida itself is a crash source**: one crash's faulting module was
  `frida-agent.dll_unloaded` at `0x9c7e0`. Attach as late as possible, prefer hooks-only
  probes, and treat a death as invalid unless the faulting module is `NewWorld.exe`. Atlas:
  `frida_agent_unload_is_a_crash_source_20261012`.
- **The player position is measured with the client's own accessor**: `nw_getPlayerPosition`'s
  handler `0x141015b30` calls `FUN_140fddfa0(&holder)` and reads
  `*(float*)(holder+0x14c/0x15c/0x16c)`. Probes `frida-player-position.py`,
  `frida-position-validate.py` (validated by calling the client's own handler). Atlas:
  `player_position_accessor_and_console_commands_20261012`.
- **W does NOT move the player — measured, 667/667 identical samples** at 0.2 s over 136 s
  containing a 10 s W hold and a 4 s S control; input reached the game (server logged 8184
  app-data events carrying 7804 channel-1 records). Atlas:
  `w_does_not_move_the_player_measured_with_the_client_accessor_20261012`.
- **`ActorMover` is server-side hub migration, NOT locomotion.** The position plumbing is
  `PlayerPositionTrackingComponent` / `PositionInTheWorldComponent` /
  `PositionalTicketingComponent` / `CameraPositionListener`. Atlas:
  `actormover_is_hub_migration_not_locomotion_20261012`.
- **The `IPositionReceiver` is never created**: `installer=0` and `register=0` in every sample
  of a whole session (18 min in-world). Atlas:
  `position_receiver_never_created_in_a_full_session_20261012`.
- **The blocker is reframed: our replay delivers to unbound client facets generally** (23 of
  the 13041 facet errors are `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`).
  Atlas: `replay_sends_to_unbound_client_facets_20261012`.
- **The 20-minute exit did not arm with gap 4 (replicated)**: 22 min 12 s in-world with
  `ActorContainerDisconnect` 0. Atlas: `exitA_gap4_replication_20261012`.
- **The IPositionReceiver machinery is data-driven**: interface vtable `0x1482eb160` referenced
  by exactly ONE site (installer `0x143f983d0`, slot +0x28 of base vtable `0x1482ea4e8`); the
  base vtable's slot +0x20 is `ret 0`. Atlas: `ipositionreceiver_vtable_layout_20261012`,
  `az_interface_decoupler_mechanism_20261012`.
- **Type names are recoverable from the binary** (`typeindex.json` + `.rdata` RTTI strings);
  `0x635` = `ActionListComponentServerFacet_ReceiveInputFromClient`, `0x1096`/`0x1097` =
  `TimeComponentClientFacet_SyncTimeChange`/`SyncDayPhase`, and the earlier "dispatch fixed"
  result was a false fix. Atlas: `wire_type_names_from_binary_20261012`,
  `input_stream_is_action_list_facet_call_20261012`,
  `position_reply_timecomponent_target_is_a_false_fix_20261012`.

Movement is the immediate user-visible deliverable. Keep the first slice narrow:
find why the existing local-player entity does not respond to input, then build
the reusable replication/authority behavior demonstrated by that trace. Avoid
starting a generic payload-codec campaign without evidence it blocks this slice.

Moving the player requires five things to be true at once, and four of them are
the same work the rest of the world needs:

| # | layer | state |
| --- | --- | --- |
| 1 | **spawn** — the entity exists client-side | world entry and possession reproduce |
| 2 | **physics components** — relevant types exist on the live player | `CharacterPhysicsComponent` and `GameRigidBodyComponent` found on the 126-component entity; activation is unknown |
| 3 | **input** — input reaches client movement logic | channel-1 `0x635` streams, but W produced no movement-family message; consumer/state change unknown |
| 4 | **connection UX** — client ALC conversation is current | red HUD warning; `+0xAA0` closed and `+0xAA8` stamp stops |
| 5 | **movement exchange** — position reaches the correct client target and server authority | reliable 4216 decodes, then dispatch fails for missing facet target |

The working plan has separate connection and movement acceptance gates. Detailed
order and pass criteria live in [`docs/ROADMAP.md`](docs/ROADMAP.md).

### Closed measurement — corrected player component list (2026-10-10)

The old claim that physics was absent used a component GUID list shifted by one
entry and is refuted. The corrected live dump found `CharacterPhysicsComponent`
and `GameRigidBodyComponent`; the client's own lookup finds both on the 126-
component player entity. This proves component presence only. It does not prove
that the body/controller is active or identify why W does not move the player.
Evidence: `local_player_components_step0_20261010` and
`reverse/probes/client/frida-player-components.py`.

### Current experiment order

1. **Resolve the physics-component disagreement.** Re-dump the same live player entity at
   spawn+4 s, +30 s and +2 min in ONE session while logging every ADD (`FUN_1413789c0`), so a
   late physics addition is caught. Use the corrected resolution (check the resolved function
   pointer, not the vtable) and prefer hooks-only probes attached at character select.
2. **Build the position work on `PlayerPositionTrackingComponent`** (on the entity) and
   `PositionInTheWorldComponent` / `PositionalTicketingComponent` / `CameraPositionListener`,
   NOT on the `ActorMover` family.
3. **Find which client object would create the `IPositionReceiver` instance** (installer and
   register both read 0); several client facets are unbound, so this is the incomplete
   local-player object graph.
4. **Measure every movement claim with the validated accessor** (`frida-player-position.py`);
   the client's other console commands (`nw_findLocalEntity`, `nw_getPlayerHealth`) give the
   same treatment to other questions.
3. Trace the missing `IPositionReceiver`/facet target for reliable type 4216.
   The reader runs, but `RMIDispatch` says its `targetLocalId` does not exist;
   decoding alone is not a successful position update.
4. Implement one behavior justified by those traces. Re-run with one variable
   changed; preserve negative results as well as wins.
5. Prove user-visible connection (red HUD warning cleared, no REP disconnect,
   in-world past 20 minutes; then a 2-hour soak) and movement (measured transform
   changes with W, stops on release, and the movement exchange succeeds).

Only if the measurements show an unknown component payload is on this path should
we perturb the 48 spawn fragments or expand per-type codec work.

### Deferred codec inventory (not the active blocker)

The spawn record carries 48 fragments: 48 distinct keys, 47 distinct types. By
measured size, 13 are 16 bytes or less, 15 are 17-64 bytes, 5 are 65-512 bytes,
10 are 513 bytes to 4 KB, and 4 exceed 4 KB. All 47 type IDs exist in the
executable; only one currently has a name. Keep this inventory for targeted
follow-up, but do not infer that an unnamed fragment contains movement state.
Only decode a fragment after a live transform/input/ALC trace shows it lies on
the failing path.

### One shortcut that is closed

The capture is a short login session: 24 of its 79 bundles are the **same 46 KB
spawn record re-sent**, and the other 54 are one-off records (sizes 78-7167 bytes,
none sharing a payload). There is **no ongoing per-entity state stream** in it,
which matches the measured W-hold sample: channel-1 `0x635` showed no measured position change, and the client emitted no movement-family message in that window.

This capture does not identify every fragment meaning, but the missing names do not prove that broad payload-codec work is the current blocker. The next measurements are the actual player transform/body-controller state, channel-1 `0x635` input consumer, ALC door, and reliable 4216 facet binding. Construct or decode a payload only when one of those traces names it.

### Current blocker, based on live evidence

- The local player entity already has `CharacterPhysicsComponent` and
  `GameRigidBodyComponent`; their presence does not prove active simulation.
- The ALC door `+0xAA0` stayed closed and the HUD response stamp `+0xAA8`
  stopped advancing. Input-response traffic and `StartMovementCommunicationMsg`
  did not open the conversation.
- W produced no movement-family messages in the sampled run. Read the transform
  directly and trace the channel-1 `0x635` consumer before choosing a fix.
- Reliable wire 4216 reaches the reader but fails RMI dispatch because its
  `targetLocalId` has no facet target. Reader success is not position
  application.
- `FUN_141763b70` is one historical lead: it ran only before world entry in a
  sampled trace. Corrected live enumeration found physics component types on the
  entity, so this gate alone does not prove the body is absent or cause movement.

The current connection/movement pass criteria and experiment order are in
[`docs/ROADMAP.md`](docs/ROADMAP.md) and [`STATUS.md`](STATUS.md).

## The three message systems (conflating them is what made this look opaque)

1. **AOI traits** — 82 traits, 2276 pairs. Server-side authority for entity and
   component state. A trait replicates state as **records carrying fragments**,
   which is the `0x08` bundle. The record id selects a handler at
   `state + 0x608 + record_id*0x10`.
2. **Client-facet RMIs** — 1783, named `<Component><Client|Server>Facet_<Method>`.
   This is the system behind the `RMIDispatch` warnings.
3. **Javelin typed messages** — 144, carrying a wire type number. Session, hub
   and movement control.

## Traps measured — do not rediscover these

- **"The parse consumes the body exactly" is necessary but NOT sufficient.**
  This cost real time twice. A model that treats the remainder as an opaque
  payload ALWAYS consumes exactly, so that check cannot discriminate. The
  distinguishing evidence is the client's own reads — measure the cursor delta
  and the nested call count. Two of my own models passed every self-consistency
  check and were still wrong.
- **Ghidra renders the 3-byte varint branch big-endian.** That would make
  `d9 a9 05` equal 1384633, larger than the 46407-byte message containing it. The
  data falsifies it; the continuation bytes are little-endian.
- **The old physics GUID list was shifted by one entry**, and the earlier
  "correction" fixed only four. The corrected live dump refuted the absence
  claim: the player entity has `CharacterPhysicsComponent` and
  `GameRigidBodyComponent`. Use `research/atlas/az-type-registry.json`; component
  presence still does not prove active simulation.
- **A loose `name\0...bare-guid` scan pairs names with unrelated neighbours.** It
  maps `Transform` to `{5D9958E9...}` (the AZ math struct) when the
  entity-component Transform is `{484AE67D...}`. Use the brace-wrapped form.
- **An unknown fragment type is dropped SILENTLY.** The client log is not a
  usable signal for "does the client know this type"; use a hook or an
  observable state change.
- **The world log accumulates sessions.** Do not filter by timestamp by eye; split
  on `listening-dtls` or delete the log before measuring.
- **`progress.json` lies** (it describes only its last pass). The `.idx` is
  authoritative.
- **`research/atlas/observed-endpoints.json` is auto-generated from a gitignored
  log, and regenerating it LOSES history** (it drops six endpoint families and
  adds a Zed editor hitting localhost:8080). The committed version is richer.
  Do not regenerate it casually.
- **Do not `git clean -fdx`** — ~4,292 ignored entries are valuable (corpus,
  toolchain, `private-client/`).
- `curl` from Git Bash does not use the Windows CA store; use PowerShell
  (`Invoke-WebRequest`), which is Schannel, like the game.

## How to run a private session

```powershell
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'   # gate 6: player possessed
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'           # replays 0x1096/0x1097; not an ALC/HUD fix
# Leave AZOTH_CHUNK_GAP_MS unset for the 4 ms default unless an A/B isolates a need to change it.
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'         # gate 8b: no resend storm
python az.py dev                                    # start the stack

python scripts/patch-dtls-disk.py apply
python scripts/private-run.py                       # drives the whole run
python scripts/patch-dtls-disk.py restore           # ALWAYS at the end
```

`python scripts/private-run.py` launches, passes the splash gate, waits for
character select, applies the world-phase patches, clicks Play and reports a
verdict. It is built for unattended work: it is how the overnight A/B runs were
done. `python scripts/private-run.py --no-launch` attaches to a running client.

Attach a probe BEFORE entering the world:
`nohup python az.py probe frida-read-sequence --timeout 500 &`

Verify a session with `Game.log` in `%LOCALAPPDATA%\AGS\New World\` (the game
ignores the launcher's log override and uses the real AppData). A transport-only
pass is `player spawn succeeds` 1, `transportError` 0, `disconnected from REP` 0.
It does not pass the HUD/ALC or movement gates.

For anything visual, use the `azoth-computer-use` skill: `python az.py shot`,
then `python scripts/shrink-image.py` — never read the raw PNG. For movement
tests, `scripts/focus-window.py` FIRST and refuse to send input if focus fails,
then `scripts/hold-key.py`. Do not use the old `bmp-diff.py` motion ratio as a
movement pass/fail signal; it produced a false positive. Read the live player
transform directly.

## Suggested order for the next session

1. Read `AGENTS.md`, current `STATUS.md`, and run `git status --short`; distinguish
   committed work from the local probes/reports.
2. Reproduce the ALC HUD warning and exit timer on a fresh client; save a correctly
   framed screenshot and direct ALC/transport measurements.
3. Measure transform and body/controller state while W is held and released.
4. Trace channel-1 `0x635` input consumption and reliable 4216 facet resolution.
5. Implement the smallest supported fix, then repeat connection and movement
   acceptance. Update the atlas, short status, handoff, and public roadmap before
   reporting the result.

## Summary

**Confirmed.** The private client enters the world and possesses the player; one
REP transport run lasted 2 h 06 min without a transport error or REP disconnect.
The red ALC/HUD warning and the 20-minute return-to-menu path are still open. Three
server-side causes of the old ~27 s transport disconnect were found and fixed,
each measured live. The Javelin container is fully decoded —
prefix varint, byte-exact state bundle, record sequence, and a two-varint fragment
header — with tests, and the server can now **build** a bundle rather than only
replay one. Three registries map the protocol: 144 Javelin messages with wire
types, 4814 AZ types, and 82 AOI traits with 2276 pairs, each generated by a
scanner that refuses to write if its hand-verified facts stop reproducing. Several
atlas facts were corrected along the way, including a systematic one-entry shift in
the physics GUID list.

**Open.** Movement is the immediate deliverable. The old “no physics component”
claim was refuted: the live player entity has `CharacterPhysicsComponent` and
`GameRigidBodyComponent`, although active simulation is not proven. W currently
produces no movement-family message, and reliable position type 4216 decodes but
fails facet-target dispatch. The ALC stamp/door and the 20-minute exit also remain
open. The next experiments and pass criteria are in `docs/ROADMAP.md`.

**Method note.** Twice this session a model passed every check it was given and was
still wrong, because "consumes the body exactly" is necessary but not sufficient — a
model with an opaque remainder always consumes exactly. The fix each time was to
stop validating the model against itself and measure what the client actually does.
Expect to need that discipline again: the fragments have no length field, so the
temptation to infer a payload layout from size alone will be strong.
