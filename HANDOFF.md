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

- Branch `main`, **7 commits ahead of `origin/main`** (`4b03eb4`). Working tree
  clean. Run `git log --oneline -8` to see them; each is a reviewable work unit.
- Build in scope: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`
  (Steam `Bin64/NewWorld.exe`, 179,204,176 B, `[RETAIL].Javelin.1.400.6031.6004151`).
- Tests: **113 world**, **24 gateway**.
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
## What is SOLVED (do not re-investigate)

1. **World entry, possession, rendered world.** Gates 1-8b in
   `research/docs/PRIVATE-CLIENT-RUNBOOK.md`.
2. **Session stability.** A run holds the world for **2 h 06 min** with
   `transportError` 0 and `disconnected from REP` 0 (previous best 0.6 min,
   long history of drops at ~27-35 s). Three causes, all server-side:
   output coupled to input (`Pearson 0.995 -> 0.180`); the UDP loop stalling
   itself (log reopen per event, 1:1 ACKs, heartbeat retried to its cap); and
   the activity clock waiting for the replay (gates 8e/8f).
3. **The protocol container, decoded.** The prefix varint, the byte-exact
   type-0x08 state bundle, the record sequence, and the two-varint fragment
   header. `services/world/src/azoth_world/javelin/varint.py` and `bundle.py`,
   with tests. The server can now READ and BUILD a bundle, not just replay one.
4. **The message/type/trait registries.** 144 Javelin messages with wire types,
   4814 AZ types, 82 AOI traits with 2276 pairs. Three self-verifying scanners
   under `reverse/tools/`.

## What is OPEN — and the reframe that matters

**Movement is not a feature to implement. It is the last thing that falls out**
once the replication protocol is complete, and every piece of that protocol is
shared with NPCs, other players and every world object. Do not plan around
"doing movement": plan around completing one mechanism.

Moving the player requires five things to be true at once, and four of them are
the same work the rest of the world needs:

| # | layer | state |
| --- | --- | --- |
| 1 | **spawn** — the entity exists client-side | works for the player; NPCs use the same path |
| 2 | **replication** — entity and component STATE flows as records and fragments | container decoded, payload codecs not written |
| 3 | **physics** — the entity has a body | nothing started |
| 4 | **input** — the client produces movement intent | the client produces nothing at all today |
| 5 | **movement family** — the server asserts and confirms position | wire types known, bodies not |

So the real objective is: **implement record/fragment replication for the
component types that matter, in priority order.** Movement, NPCs, world state and
other players are all the same mechanism applied to different types. That is why
this is one body of work and not five.

### Step 0 — re-verify the diagnosis first (cheap, one session)

The claim "the local player has no physics component" (`local_player_has_no_physics_20261004`)
was measured by searching for a list of component GUIDs that is **shifted by one
entry**, and `physics_component_guids_corrected_20261005` fixed only four of them.
`CharacterPhysicsComponent` was recorded as `{B1237004-14E1-4327-8774-D2C5796230E7}`,
which **does not exist in this build at all**. So the conclusion is **UNPROVEN**:
we do not actually know that physics is missing. Use
`research/atlas/az-type-registry.json`.

Re-dump the live player entity component list with the corrected GUIDs. Both
outcomes are useful: if physics really is missing, we now know exactly which GUID
to hunt for; if it is present, the blocker is the body gate and input filtering,
and the physics payload work may not be needed at all. An existing probe can do
this, so it costs one session.

### The ranked experiments, cheapest first

| # | experiment | what it settles | new tooling? |
| --- | --- | --- | --- |
| 0 | Re-dump the live player component list with the corrected GUIDs | whether physics is actually missing | no, probe exists |
| 1 | Hook the vtable slot that would call the body gate; log what has to be present | what triggers `FUN_141763b70` — the hard unknown | small probe |
| 2 | Perturb each of the 48 fragments in the spawn record, one at a time, and observe the client | which fragment is position, which is physics | no, container now buildable |
| 3 | Hook the type reader (vtable `+0x90`) per type | the payload format, type by type | template exists |

Experiment 2 is only possible **because** the container is now understood: we can
rebuild a bundle with one changed payload and the client will still parse it. That
turns "which of 47 types is position" from a guess into a search.

### What the codec work actually looks like

The spawn record carries 48 fragments: 48 distinct keys, 47 distinct types. By
measured size, 13 are 16 bytes or less, 15 are 17-64 bytes, 5 are 65-512 bytes,
10 are 513 bytes to 4 KB, and 4 exceed 4 KB (17176, 5913, 4843, 4754 bytes).
**28 of 48 are 64 bytes or smaller** — likely plain scalars and vectors, the
tractable end. The four large ones will be the expensive ones.

All 47 types **do exist in the executable** (verified: 47 of 47 are present), so
they are real client types. What is missing is their **names**: these descriptors
use a different layout from the component and message regions, so the name is not
recoverable by adjacency, and only 1 of the 47 currently has a name. Without names
we cannot tell which type carries position and which carries physics — which is
what makes experiment 2, an empirical search, more valuable than more scanning.

### One shortcut that is closed

The capture is a short login session: 24 of its 79 bundles are the **same 46 KB
spawn record re-sent**, and the other 54 are one-off records (sizes 78-7167 bytes,
none sharing a payload). There is **no ongoing per-entity state stream** in it,
which matches the live measurements — the channel-1 player stream never changes and
the client emits no movement message in either direction.

Careful with the conclusion: this does **not** prove that no captured record carries
position, because the 47 spawn types are still unidentified and we cannot rule any of
them out. What it does mean is that there is no authoritative updating position to
mine from the capture, so a physics or position fragment must be **constructed**
rather than replayed. That is exactly why the payload codecs are the crux.

### Where the difficulty actually is

- The container was the part blocked on **unknowns**, and it is done. Bundles can
  now be built, so every further experiment is a measurement rather than a guess.
- The remaining work is a **semantics layer**: what the 47 types mean and how each
  serializes. A long tail, but a searchable one.
- The **body gate** is the one piece with no visible path yet: `FUN_141763b70` is
  reached by a dispatch nothing points at, and an unreached gate means no body
  regardless of how correct the payloads are. Experiment 1 targets exactly this.

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
- **The old physics GUID list is shifted by one entry**, and the earlier
  "correction" fixed only four. `CharacterPhysicsComponent` was recorded as
  `{B1237004...}`, which does not exist in this build. Use
  `research/atlas/az-type-registry.json`. The conclusion "the player has no
  physics component" is therefore **UNPROVEN** — it came from searching for ids
  that do not exist.
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
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'           # gate 7: no red cable
$env:AZOTH_CHUNK_GAP_MS             = '20'          # gate 8: no post-spawn drop
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
ignores the launcher's log override and uses the real AppData). A healthy
session: `player spawn succeeds` 1, `transportError` 0, `disconnected from REP` 0.

For anything visual, use the `azoth-computer-use` skill: `python az.py shot`,
then `python scripts/shrink-image.py` — never read the raw PNG. For movement
tests, `scripts/focus-window.py` FIRST and refuse to send input if focus fails,
then `scripts/hold-key.py` and `scripts/bmp-diff.py`. The "no movement" threshold
is a motion ratio of ~0.12x.

## Suggested order for the next session

Work the protocol, not "movement". They are the same task, and the protocol one
is the one that also gives you NPCs, world state and other players.

1. `git log --oneline -10` and read the commits; then `STATUS.md` and this file.
2. Read `research/docs/JAVELIN-PROTOCOL.md` sections 2d-2g and
   `services/world/src/azoth_world/javelin/bundle.py`. That is the container, and
   everything else builds on it.
3. **Step 0 above**: re-dump the player component list with the corrected GUIDs.
   One session, existing probe, and it decides whether physics work is even needed.
4. **Experiment 1**: hook the vtable slot that would reach the body gate. This is
   the other hard unknown and it is independent of the codec work, so it can run
   in parallel with it.
5. **Experiment 2**: perturb the 48 spawn fragments one at a time. This is how the
   47 types get identified without names, and it is cheap now that bundles can be
   built.
6. Then the per-type payload codecs (experiment 3), starting with `record_id` 1 and
   the small fragments — 28 of 48 are 64 bytes or less.
7. Objective 3 opportunistically: a real character UUID, stop the facet RMI misses,
   the two unresolved wire types.

## Summary

**Solved.** The private client enters the world, possesses the player, renders the
world with NPCs and the full HUD, and holds the session for **over two hours** with
zero transport errors. Three server-side causes of the old ~27 s disconnect were
found and fixed, each measured live. The Javelin container is fully decoded —
prefix varint, byte-exact state bundle, record sequence, and a two-varint fragment
header — with tests, and the server can now **build** a bundle rather than only
replay one. Three registries map the protocol: 144 Javelin messages with wire
types, 4814 AZ types, and 82 AOI traits with 2276 pairs, each generated by a
scanner that refuses to write if its hand-verified facts stop reproducing. Several
atlas facts were corrected along the way, including a systematic one-entry shift in
the physics GUID list.

**Open, and reframed.** The goal is not "movement" but the completion of
record/fragment replication; movement is what falls out when it is done, and the
same mechanism gives NPCs, world state and other players. Two things stand between
here and there: the **per-type payload codecs** (a searchable long tail, 47 types,
28 of them 64 bytes or smaller) and the **body gate** `FUN_141763b70`, which is
reached by a dispatch nothing points at and has no visible path yet. And before
either, one cheap correction: the claim that the player has no physics component
rests on a GUID list that is shifted by one entry, so it is unproven and needs
re-measuring.

**Method note.** Twice this session a model passed every check it was given and was
still wrong, because "consumes the body exactly" is necessary but not sufficient — a
model with an opaque remainder always consumes exactly. The fix each time was to
stop validating the model against itself and measure what the client actually does.
Expect to need that discipline again: the fragments have no length field, so the
temptation to infer a payload layout from size alone will be strong.
