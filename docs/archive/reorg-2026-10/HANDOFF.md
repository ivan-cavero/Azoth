# Handoff — Azoth (New World private server)

Session handoff for a fresh agent with **zero context**. Read `AGENTS.md`,
[`STATUS.md`](STATUS.md) and this file first, then the focused references it
points at. This file was rewritten on 2026-10-12 and replaces all earlier
versions: several premises in the previous handoff were refuted by measurement
(see "Corrections — do not reuse these premises").

Working directory: the repository root. Branch `main`.

## Hard rules

- **Do not commit or push unless the user explicitly asks.** Everything below IS
  committed and pushed as of the rewrite (`c5b5c9a`), but the rule stands for new
  work. The user granted a one-off authorization to commit/push this session.
- **Steam is read-only.** Never delete, move, modify or hardlink anything under the
  Steam install. Losing `assets/*.pak` (~76 GB) once cost a full re-download. The
  private client is a **copy** at `private-client/runtime/Bin64/NewWorld.exe`;
  patches apply to that copy only, and `python scripts/patch-dtls-disk.py restore`
  puts it back byte-identical (verify with `... check`).
- **Do not `git clean -fdx`** — ~4,300 ignored entries are valuable (corpus,
  toolchain, `private-client/`).
- Run tests only to validate a change; they are fast (`python az.py world test`,
  `python az.py gateway test`). Do not add a test framework.
- Keep raw captures, client files, generated decompilation and secrets in the
  ignored locations. Durable facts go in `research/atlas/`, never only in chat.
- Docs and code are in English. `docs/sessions/` history stays in Spanish.

## Repository state at this handoff (verified)

- `git status --short` is **empty**; `HEAD == origin/main == c5b5c9a`. Two commits
  landed this session:
  - `99588f3` — "measure the live player, name its components, and stop trusting
    guesses" (92 files),
  - `c5b5c9a` — "resolve the physics claim, and show the position path is
    replicated state".
- `/reverse/sessions/` was added to `.gitignore` this session: it holds **469 MB**
  of raw probe captures (one file is 464 MB) that must never be committed.
- **Build in scope:** SHA-256
  `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`
  (Steam `Bin64/NewWorld.exe`, 179,204,176 B, `[RETAIL].Javelin.1.400.6031.6004151`,
  image base `0x140000000`). The DTLS-patched private copy has a different hash
  (`537403d49cd24e78a1a6f320ae2e147f995c92c906bf41160f21af3bf49d899a`); that is
  expected and it is restored to the Steam hash when idle.
- Tests, re-run at this handoff: **130 world OK** (2 skipped), **24 gateway OK**.
- `research/atlas/client-functions.json`: **194 entries**. Registries:
  **144** Javelin messages, **4818** AZ type entries (4814 names), **82** AOI traits
  with **2276** pairs. Decompilation campaign manifest: **50** targets across 6
  phases (`research/atlas/decomp-campaign.json`).
- Corpus for this build: 423,579 `.pdata` ranges, **423,542 ok / 37 fail**
  (20 timeouts, 10 mid-function varnode fragments, 6 payload-cap, 1 address-space).
  It does **not** cover 13,943 leaf `.text` functions with no unwind info — reach
  those with `decomp.py --range`, not `--target`.
- Toolchain: `.\az.ps1 setup` (or `python az.py setup`) installs checksum-verified
  CPython, Ghidra 12.1.4 and the JDK into ignored `.azoth/`. On an existing machine
  run `python az.py migrate` once, after closing NewWorld.

### On a fresh machine

Ignored, therefore NOT in git: `.azoth/` (toolchain, venv, logs), `private-client/`
(game copy, profile, runtime), `reverse/builds/` (corpus, Ghidra project),
`research/sessions/`, `reverse/sessions/`, `services/gateway/traffic.jsonl`,
`services/world/rep_traffic.jsonl`. After cloning: `.\az.ps1 setup`, then
`python az.py migrate` if migrating old per-user state, then
`python az.py re corpus` if you need decompilation. Everything committed is
self-contained: code, docs, tests and the atlas registries.

**Expensive to regenerate.** `reverse/builds/<sha256>/` is ~1.6 GB:
`corpus/` 1.2 GB (resumable; rebuild on demand rather than copy), `ghproj/` 459 MB
(analyzed Ghidra project), `xrefmap.json` 12 MB, `campaign/` 2.2 MB, and
`functions/` **106 KB**. To move work between machines, carry `functions/` +
`campaign/` + `campaign-state.json` + `xrefmap.json` (~14 MB) — that is every
specific decompile this project has done.

**Not regenerable:** session evidence under `research/sessions/` (427 MB) and
`reverse/sessions/` (469 MB) records observations of specific runs. Because raw
captures stay out of git, a measurement is invisible from the other machine unless
it is written into the atlas with its `found_by` — which is what the atlas entries do.

### Two traps found earlier

- `services/world/rep_traffic.jsonl` grows to multiple GB (2.4 GB measured once).
  It is a debugging log, not state: delete it rather than carrying it.
- `scan-az-types.py` used to degrade **silently** when `typeindex.json` was
  missing, writing a registry with every `in_type_table: false`. It now refuses to
  write.

## Corrections — do not reuse these premises

Every item below was measured or located this session and **replaces** what an
older document (including the previous handoff) says. The atlas entries named are
the authoritative records.

1. **The live player entity does NOT carry `CharacterPhysicsComponent` or
   `GameRigidBodyComponent`.** Same entity sampled at ~4 s, +30 s and +120 s after
   spawn: 126 components, 126/126 resolved, both absent every time, all controls
   present; the component-ADD hook was live (24 adds, none on the player entity).
   The old claim came from **misreading its own capture**: that capture records
   `physics_asked: {CharacterPhysicsComponent: "null", GameRigidBodyComponent:
   "null"}` and lists both in `lost_named`, and the entry read `asked_named` as the
   found list. That capture's entity also had only `hits=21` — the short-lived/freed
   126-component entity, not the live one.
   Atlas: `physics_components_absent_RESOLVED_20261012` (and
   `local_player_components_step0_20261010` is corrected + `superseded_by`).
2. **`ActorMover` is server-side HUB MIGRATION, not locomotion.** Its strings are
   `Sending CommitMovement for actor`, `Destination hub timed out before receiving
   CommitMovement or AbortMovement…`, `DelayMigrationsMsg`, `MoveActorToHubMsg`.
   Therefore `StartMovementCommunicationMsg` (wire 726) was the wrong lever from
   the start — consistent with it changing nothing even when sent reliably on
   channel 0. Atlas: `actormover_is_hub_migration_not_locomotion_20261012`.
3. **The position reply's "dispatch fixed" result was a FALSE FIX.** The target blob
   that makes the RMI dispatch succeed (`93a3e477cb5fd51e`) is the client's
   **`TimeComponentClientFacet`** local id, so the position was delivered to a
   time-sync facet. It replaced a loud failure (13012 facet errors, 0/601 dispatch)
   with a silent wrong-object delivery (642/642, 0 errors) and `FUN_143f97bf0` still
   returned 0. Atlas: `position_reply_timecomponent_target_is_a_false_fix_20261012`.
4. **`0x1096`/`0x1097` are `TimeComponentClientFacet_SyncTimeChange` /
   `SyncDayPhase`, not "input responses".** So the `AZOTH_REPLAY_INPUT_RESPONSE`
   lever replays TIME SYNC. **`0x635` (index 1589) is
   `ActionListComponentServerFacet_ReceiveInputFromClient`** — the client's ALC input
   stream, 19676/19676 records in one session with a valid `[crc32][len]` container,
   all targeted at the full 16-byte actor id. The INPUT direction already works.
   Atlas: `wire_type_names_from_binary_20261012`,
   `input_stream_is_action_list_facet_call_20261012`.
5. **Screenshots and byte-diffs are not movement measurements.** The old `bmp-diff`
   "motion ratio" produced a false positive (a coherent translation makes the best
   shifted match *better* than the unshifted one, i.e. ratio > 1, so the old 0.94
   meant "did not translate"). Diffing the `Transform` component's first 0x100 bytes
   is also useless: that object is a pointer/counter header.
6. **The 20-minute exit is armed by `AZOTH_CHUNK_GAP_MS`**, and the corrected exit
   patch is exercised but is **not a session fix.** Gap 20 (replay 29 s) armed the
   teardown delegate at exactly **20:00.398**; gap 4 (replay 10 s) did not arm it at
   all (22 min 12 s in-world, `ActorContainerDisconnect` 0 — replicated twice). With
   the patch applied the delegate ran and the call at `0x14100425F` was skipped
   (`exiting to main menu` 0, `Cleanup()` 0), but the same delegate already tears the
   connection down at `0x141004230` *before* the patched call, so the client stopped
   sending traffic at 20:00.398 and the on-screen world was a frozen frame.
   Atlas: `exitA_gap20_run_outcome_20261011`, `chunk_gap_decides_the_20minute_arm_20261011`,
   `exitA_gap4_replication_20261012`, `exit_delegate_call_site_verified_20261011`.
7. **A Frida attach can crash the client.** One crash's faulting module was
   `frida-agent.dll_unloaded` at `0x9c7e0`. Others are `ntdll.dll` at `0x1662b7`
   (three times) and `0xc4a0f`. Atlas: `frida_agent_unload_is_a_crash_source_20261012`.
8. **`inCode(vtable)` is the wrong check on this build.** A component's VTABLE lives
   in `.rdata` (`r--`) while the function pointer stored in it lives in `.text`.
   Checking the vtable rejects **every** component (126/126 as `badVtbl`). Check the
   resolved **function pointer**.

## What is confirmed (still true)

1. **World entry and possession reproduce.** The private client renders the world and
   possesses the player (`player spawn succeeds, in game`, state `InGame`).
2. **REP transport is durable.** One measured run survived **2 h 06 min** with
   `transportError` 0 and `disconnected from REP` 0. The user-visible red ALC/HUD cable
   stayed RED throughout — transport uptime is **not** connection health.
3. **The protocol container is decoded,** with tests:
   `services/world/src/azoth_world/javelin/varint.py` (prefix varint) and
   `bundle.py` (byte-exact type-0x08 state bundle: `[marker][01][varint SEQ][6
   invariant bytes][varint length]` then a **record sequence**, each record
   `[u8 record_id][u8 fragment_count][fragments…]`, each fragment
   `[varint KEY][varint TYPE_INDEX][type-specific payload]` with **no length field**).
   The server can READ and BUILD a bundle, not only replay one.
4. **Registries exist and self-verify** (three scanners under `reverse/tools/`):
   144 Javelin messages with wire types, 4818 AZ type entries, 82 AOI traits.
5. **The client's own instrument for position exists and works** (see below).

## Current blocker, precisely measured

### Movement: input leaves the client, the position never changes

Measured with the client's own accessor (see "Instruments"), on a fresh in-world
session: **667 of 667 samples identical** at 0.2 s over a 136 s window that contained
a **10 s W hold** and a 4 s S control. Position stayed
`(9343.6416, 2786.7327, 87.538)`. In the same window the world server logged **8184
app-data events carrying 7804 channel-1 records** — the input demonstrably reached the
game. Atlas: `w_does_not_move_the_player_measured_with_the_client_accessor_20261012`.

**Why — the position path.** The authoritative world position is **replicated STATE,
not an RMI**, and the client-side facets that would own it are **missing** on the
local player entity:

- present: the bare `PlayerPositionTrackingComponent` (`62620B33-6F37-418B-9C4F-62AD6058D54D`);
- **absent**: `PlayerPositionTrackingComponent{Client,Server}Facet`,
  `PositionInTheWorldComponent{Client,Server}Facet`,
  `PositionalTicketingComponent{Client,Server}Facet`, `CameraComponent`, `IPositionReceiver`;
- static agrees that no RMI can be the path: `PlayerPositionTrackingComponent` carries
  only AI spawn-manager **debug** messages (wires 357, 2780, 6635) and
  `PositionInTheWorldComponent{Client,Server}Facet` have **no registered messages at
  all**, while `PositionInTheWorldComponentServerFacet::InitializeReplicatedFields`
  and `InstallRegistrationHook<VPositionInTheWorldReplicatedState, MB>` exist → the
  position is AOI replicated state (`MB::PositionInTheWorldReplicatedState`).

This is the **same failure class** as the 23 unbound
`GlobalStorageComponentClientFacet_ReceiveStorageSearchItems` messages in our replay
and as the never-created `IPositionReceiver`: **the client-side facets for the local
player are not created.** Atlas: `position_facets_absent_on_the_live_entity_20261012`,
`position_state_may_arrive_as_replicated_state_not_rmi_20261012`,
`replay_sends_to_unbound_client_facets_20261012`,
`position_receiver_never_created_in_a_full_session_20261012`.

### Connection: the HUD cable is an ALC timeout, not a REP verdict

The icon (left edge, vertically centred: a cable with a red X and a warning triangle)
goes absent → amber → red as `now - *(conn+0xAA8)` crosses ~2 s then ~15 s. It is
**not recorded in `Game.log`** — `OnLocalNetworkConnectionWarning`, `transportError` and
`disconnected from REP` say nothing about it, and three diagnoses went wrong by quoting
those counters. The only instrument that sees it is a screenshot
(`scripts/watch-indicator.py` classifies the box RED/YELLOW/absent). Measured live: the
ALC door `+0xAA0` stayed **0** on both client classes and the `+0xAA8` stamp stopped
advancing, while REP transport was healthy. The handshake producer remains **unknown**;
`StartMovementCommunicationMsg`, replayed input responses and position replies did not
open it. Atlas: `hud_cable_icon_is_not_the_log_20261010`,
`alc_pointer_never_opens_live_20261011`, `start_movement_does_not_open_alc_20261011`.

### Acceptance gates (unchanged in intent, now measurable)

- **Connection:** the real HUD cable clears and stays clear, REP has no transport
  error, and the client stays in-world beyond the 20-minute threshold; prove 30 minutes,
  then a 2-hour soak.
- **Movement:** the local transform changes in the expected direction while W is held,
  stops on release, and produces the expected client/server exchange; then turning and
  collision. Use the validated accessor as the primary proof.

## Instruments — what now works (and the traps inside them)

Eight probes were added or fixed this session. All are under
`reverse/probes/client/` and run with `python az.py probe <name>`.

| probe | what it does | status |
| --- | --- | --- |
| `frida-player-position.py` | **reads the player position with the client's own accessor** (`FUN_140fddfa0(&holder)` → floats at `holder+0x14c/0x15c/0x16c`). This is the movement instrument. | **validated** |
| `frida-position-validate.py` | calls the client's own console-command handler `0x141015b30` and watches its printer `0x141022a90` fire; cross-checks the accessor against the client's own output. | validated |
| `frida-player-components-full.py` | dumps and names all components of the live entity, and asks the client's lookup for chosen GUIDs (both byte orders). | works |
| `frida-physics-timeline.py` | three snapshots of the same entity + **every** component ADD (`FUN_1413789c0`). | works |
| `frida-position-receiver.py` | hooks the `IPositionReceiver` installer `0x143f983d0`, register-by-name `0x143f98300`, and the delivery as control; reads the AZ reflection registry global. | works |
| `frida-position-target.py` | scans the RMI target registry (37063 targets, 225 distinct vtables) asking each vtable whether it answers `IPositionReceiver`. | works (calls client code — riskiest) |
| `frida-rmi-targets.py` | dumps the RMI target registry (capacity, keys, objects, vtables). | works |
| `frida-lookup-diag.py` | histogram of the component-lookup calls, to calibrate the entity gate. | works |
| `frida-movement-state.py` | earlier attempt; **superseded** by `frida-player-position.py`, kept because its comments record the two failed resolution approaches. | superseded |

**The client's console commands are a usable toolbox.** `nw_getPlayerPosition`
("print player position to the screen") and `teleport` ("unlike goto it actually sets
the player rotation correctly", `teleport x y z`) are registered in a table where each
entry does `lea rdx,[name]; lea r8,[handler]; call [rax+0x110]`. The handler is found
by scanning for the rip-relative `lea` of the command-name string. Also available:
`nw_findLocalEntity`, `nw_findEntityBySlicePath`, `nw_getHeightAtCoords`,
`nw_getCameraDirection`/`nw_setCameraDirection`, `nw_getPlayerHealth/Stamina/Mana/Food`,
`lc_serverCommand`, `lc_spawnSlice*`. Atlas:
`player_position_accessor_and_console_commands_20261012`.

### Method traps that cost real time — do not repeat

- **A component's VTABLE is in `.rdata`; its slot-0 function pointer is in `.text`.**
  Check the **function pointer**. Checking the vtable rejected 126/126 components.
- **Select the live entity by MOST LOOKUPS**, not first-seen. During a load two
  126-component entities appear: a short-lived/freed one (~21 hits) and the live one
  (826–1955 hits).
- **Frida's `context.xmm0/1/2` serialise to `{}` on this build**, so printed doubles
  cannot be read that way; call the accessor instead.
- **`parse_datagram` on the logged `raw` fails** (`payload truncated: need 2048 bits,
  have 896`). Raw inbound datagrams must go through `parse_envelope` first, and be
  LZ4-decompressed when the envelope is `0x81`.
- **Hook hot functions sparingly.** The component lookup is called ~19k times in a few
  minutes; a heavy callback stalls the client thread and distorts the measurement.
- **Consult the module that faulted** in Windows Application event 1000 before reading
  a session death as client behaviour (one was Frida's own agent unload).

## How to run a private session (updated)

```powershell
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'   # gate 6: player possessed
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'           # replays TimeComponentClientFacet time sync (mislabeled)
# Leave AZOTH_CHUNK_GAP_MS unset for the 4 ms default: 20 ms arms the 20-minute exit.
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'         # gate 8b: no resend storm
python az.py dev                                    # start gateway + world + Caddy

python scripts/patch-dtls-disk.py apply
python scripts/private-run.py                       # drives the whole run
python scripts/patch-dtls-disk.py restore           # ALWAYS at the end
```

- **Wait for the CMS manifest to answer 200 before launching.** `python az.py dev`
  returns before Caddy binds :8080; launching in that window makes the manifest 502 and
  the client stalls on the Aeternum splash with `Auth manager does not exist`. Check
  with PowerShell `Invoke-WebRequest` (Schannel, like the game — Git Bash `curl` uses
  its own CA bundle and gives false negatives).
- **Attach probes at character select, not at the title.** Use
  `python scripts/private-run.py --no-play` (drives to character select, applies the
  world-phase patches, stops), then attach the probe, then click Play. Attaching during
  the splash/title phase has crashed the client.
- Prefer **hooks-only** probes where a hook answers the question.
- A world A/B needs a **fresh `NewWorld.exe`**: a failed attempt destroys that process's
  `ClientContext`. Treat counters as meaningful only after `Game.log` shows
  `ProcessPendingReliableMsgQueue processing … messages`. Confirm a run with
  `player spawn succeeds` 1, `transportError` 0, `disconnected from REP` 0 — a
  transport-only pass, which does **not** pass the HUD or movement gates.
- `Game.log` lives in `%LOCALAPPDATA%\AGS\New World\` (the game ignores the launcher's
  log override). Timestamps are UTC in the current build. Rotated copies land in
  `LogBackups/`; a session's own log survives there after the next start.
- Visual work: `python az.py shot`, then `python scripts/shrink-image.py` — never read
  the raw PNG. For input: `scripts/focus-window.py` first (refuse to send keys if focus
  fails), then `scripts/hold-key.py`.
- Watch a run with `scripts/watch-session.py` (both sides, one clock) and
  `scripts/watch-indicator.py` (the HUD cable box). Do not edit an append-only service
  log while its service runs.

## Next steps, in order

1. **Find what makes the client create/bind a client-side facet for a replicated
   component.** Everything else about movement waits on this. Concretely: identify which
   of the spawn record's **48 captured fragments** declares the position component's
   replicated fields, then check whether our replay actually delivers it. Evidence trail:
   `position_facets_absent_on_the_live_entity_20261012`,
   `position_state_may_arrive_as_replicated_state_not_rmi_20261012`,
   `replay_sends_to_unbound_client_facets_20261012`.
2. **Do not write another position RMI payload, and do not re-run
   `StartMovementCommunicationMsg`.** Both are measured dead ends (`ActorMover` is hub
   migration; the position families define no message surface).
3. **Measure every movement claim with `frida-player-position.py`.** The client's other
   console commands give the same treatment to other questions.
4. **Arm-side 20-minute fix only if it ever arms:** hook the deferred-action enqueue
   (`FUN_14107fb40`) rather than patching the exit. With the 4 ms default it does not arm
   at all (replicated twice).
5. Keep the ALC handshake producer as a separate open item: the door `+0xAA0` never
   opened and no tested message opened it.

## Key addresses (build 8654f01d, image base 0x140000000)

| what | VA |
| --- | --- |
| player position accessor (`&holder`; floats at +0x14c/+0x15c/+0x16c) | `0x140fddfa0` |
| `nw_getPlayerPosition` command handler | `0x141015b30` |
| `teleport` command handler → set position | `0x141020a40` → `0x140fbf3b0` |
| console print helper (`&fmt, x, y, z`) | `0x141022a90` |
| component lookup `(entity, typeId*)` | `0x1413fb700` |
| component ADD to entity | `0x1413789c0` |
| RMI dispatch (target local-id lookup) | `0x1416bcba0` |
| 4216 delivery (queries `IPositionReceiver`) | `0x143f97bf0` |
| `IPositionReceiver` QueryInterface (returns `this`) | `0x143fadd00` |
| interface vtable (slot +0x20 = QI) | `0x1482eb160` |
| family base vtable — **slot +0x20 is `ret 0`**, +0x28 installs the vtable | `0x1482ea4e8` |
| interface installer / register-by-name | `0x143f983d0` / `0x143f98300` |
| interface GUID getter (`IPositionReceiver` string at `0x1482ea938`) | `0x143fb2b90` |
| AZ interface-reflection registry (global at `0x14a313ff8`) | `[rip+0x637bce0]` @ `0x143f98311` |
| 20-min teardown delegate / the call the patch NOPs | `0x141004100` / `0x14100425f` |
| `CGame::ActorContainerDisconnect` (11 callers) | `0x146420610` |
| deferred-action queue drain (the enqueue to hook) | `0x14107fb40` |
| HUD cable per-frame stamp read | `0x14486c740` |

## The three message systems (conflating them made this look opaque)

1. **AOI traits** — 82 traits, 2276 pairs. Server-side authority for entity and component
   state. A trait replicates state as **records carrying fragments** = the `0x08` bundle.
   The record id selects a handler at `state + 0x608 + record_id*0x10`.
2. **Client-facet RMIs** — 1783, named `<Component><Client|Server>Facet_<Method>`. This is
   the system behind the `RMIDispatch` warnings, and the one whose client-side targets are
   missing.
3. **Javelin typed messages** — 144, carrying a wire type number. Session, hub and
   (as now known) hub-migration control.

The message→interface wiring is AZ's interface decoupler:
`RegisterInterfaceDecoupler<Interface>` + `InstallRegistrationHook<Msg, Interface>`, with
MSVC-mangled names surviving in `.rdata` — which is how the families above were mapped.
Atlas: `az_interface_decoupler_mechanism_20261012`, `ipositionreceiver_vtable_layout_20261012`.

## Other traps measured — do not rediscover

- **"The parse consumes the body exactly" is necessary but NOT sufficient.** A model that
  treats the remainder as an opaque payload ALWAYS consumes exactly. The discriminating
  evidence is the client's own reads (cursor delta and nested call count). Two models
  passed every self-consistency check and were still wrong.
- **Ghidra renders the 3-byte varint branch big-endian.** The data falsifies it; the
  continuation bytes are little-endian.
- **A loose `name\0…bare-guid` scan pairs names with unrelated neighbours.** It maps
  `Transform` to `{5D9958E9…}` (the AZ math struct) when the entity-component Transform is
  `{484AE67D…}`. Use the brace-wrapped `{GUID}` form. Component names are best read from
  `research/atlas/az-type-registry.json` by GUID.
- **An unknown fragment type is dropped SILENTLY.** The client log is not a usable signal
  for "does the client know this type"; use a hook or an observable state change.
- **The world log accumulates sessions.** Split on `listening-dtls` or delete it before
  measuring; restart the world server when its peer table has stale sessions.
- **`progress.json` lies** (it describes only its last pass); the `.idx` is authoritative.
- **`research/atlas/observed-endpoints.json` is auto-generated from a gitignored log.**
  It lost six endpoint families when regenerated on 2026-10-07. It was regenerated again
  this session and verified to lose none (71→72, only adds `/live.json`), but diff the
  endpoint families before committing it.
- **When an atlas entry's claim matters, re-read its source capture.** The physics
  disagreement was resolved by reading the capture the entry was written from: the entry
  was a wrong summary of correct evidence.

## Summary

**Confirmed.** The private client enters the world and possesses the player; REP transport
survived 2 h 06 min with no transport error. The protocol container is fully decoded with
tests, and the server can build state bundles, not only replay them. Three registries map
the protocol, each generated by a scanner that refuses to write if its hand-verified facts
stop reproducing. The client's **own position accessor** is now the movement instrument,
and it has produced the first honest measurement: **W does not move the player** — 667/667
identical samples while the input demonstrably reached the game.

**Corrected this session (do not reuse the old premises).** The live player entity does
**not** carry `CharacterPhysicsComponent`/`GameRigidBodyComponent` (the old claim misread
its own capture). `ActorMover` is server-side hub migration, not locomotion. The
"position dispatch fixed" target was a false fix (a `TimeComponentClientFacet` id).
`0x635` is the ALC input facet call; `0x1096`/`0x1097` are time sync. The 20-minute exit is
armed by the replay gap and the corrected patch is not a session fix. A Frida attach can
crash the client.

**Open.** Movement is the immediate deliverable and its blocker is now well posed: the
authoritative position is replicated state, and the client-side facets that would own it
are never created on the local player — the same failure class as the unbound
`GlobalStorageComponentClientFacet` and the missing `IPositionReceiver`. The next step is
to find what makes the client create/bind a client-side facet for a replicated component,
starting from the spawn record's 48 fragments. The ALC handshake producer and the HUD cable
remain a separate open gate. Pass criteria and sequencing live in
[`docs/ROADMAP.md`](docs/ROADMAP.md) and [`STATUS.md`](STATUS.md).

**Method note.** This session's most valuable outputs were corrections, and each came from
refusing to trust a summary: re-reading a capture refuted the physics claim, disassembling
the body refuted the "`ret 0` means no delivery" reading, and validating an accessor against
the client's own command output turned a derived offset into a measurement. Expect to need
that discipline again — the spawn fragments still have no length field, so the temptation
to infer a payload layout from size alone will be strong.
