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

## What is OPEN — the next objectives, in priority order

### Objective 1: the per-type payload codec (the long tail, and the unlock)

The container is understood down to the fragment; what is missing is the
**payload encoding for each component type**. A fragment is
`[varint KEY][varint TYPE_INDEX][payload]` with NO length field — the length is
implied by the type, because the reader consumes the payload through the type
object's vtable `+0x90`. So for a given `record_id`, `key` and `type`, the
question is: what bytes does that component's state serialize to?

**The route in is the technique that just worked**, and it is already written:
hook the type's reader and log what it consumes. `reverse/probes/client/frida-read-sequence.py`
and `frida-fragment-grammar.py` are the templates. Suggested first target:
record_id 1 (the local-player metadata slot, `FUN_141717fc0`), whose fragments
are the ones that matter for possession.

### Objective 2: give the local player a body (movement)

**Measured 2026-10-10, and it reframes the problem:** holding W produces **no
movement message in either direction**. The channel-1 local-player stream is
byte-identical across 3038 records (masking the rolling counter at offset 0,
only two bytes ever differ), and the client's own `teleport_player` command does
not move the player either. **Nothing moves in the client at all.** So the
server cannot unblock movement by replying to a client message — the client
never sends one. The server must CAUSE the body to exist.

The spawn path is **four steps plus a separate physics registration**, and the
capture contains only the first:

1. client asks: `PlayerSpawnPointRequestTrait::RequestPlayerSpawnPointMsg`
2. server answers: `PlayerSpawnPointResponseTrait::ReceivePlayerSpawnPointSuccessMsg`
3. manager runs: `PlayerManagerTrait::ProcessSpawnQueueMsg`
4. body created: `PrefabSpawnRequestTrait::RequestSpawnPrefabMsg`
5. physics registered separately: `PhysicsTrait::RegisterCharacterMsg` /
   `RegisterCharacterWithRepulsorsMsg`

The function that would build the movable body, `FUN_141763b70`, runs **once at
process startup and never again** — it is not failing, it is not reached.

### Objective 3 (small, do it while you are there)

- Serve a real character UUID; the client sends and logs
  `11111111-1111-1111-1111-111111111111`.
- Stop sending RMIs for facets the client lacks (the 23 x
  `RMIDispatch: facet target ID couldn't be found` warnings).
- The two unresolved wire types: `ActorQueryMsg`, `RoutingUnsubscribeMsg`.

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

1. `git log --oneline -8` and read the commits; then `STATUS.md`.
2. Read `research/docs/JAVELIN-PROTOCOL.md` sections 2d-2g and
   `services/world/src/azoth_world/javelin/bundle.py`.
3. Start Objective 1 (the per-type payload codec) for record_id 1. That is the
   prerequisite for Objective 2 and the only remaining unknown in the container.
4. Then Objective 2, using the four-step spawn plus physics registration.
5. Objective 3 opportunistically.

## Summary

**Solved.** The private client enters the world, possesses the player, renders
the world with NPCs and the full HUD, and holds the session for **over two
hours** with zero transport errors. Three server-side causes of the old ~27 s
disconnect were found and fixed, each measured live. The Javelin container is
fully decoded — prefix varint, byte-exact state bundle, record sequence, and a
two-varint fragment header — with tests, and the server can now build a bundle
rather than only replay one. Three registries map the protocol: 144 Javelin
messages with wire types, 4814 AZ types, and 82 AOI traits with 2276 pairs, each
generated by a scanner that refuses to write if its hand-verified facts stop
reproducing. Along the way, several atlas facts were corrected, including a
systematic one-entry shift in the physics GUID list that had made a prior
conclusion unsound.

**Open.** Movement. Measured precisely: the client emits no movement message at
all, its channel-1 player stream never changes, and even its own teleport command
does not move the player — so nothing moves client-side, and the server must
cause the body to exist rather than answer a message. The body needs a four-step
spawn handshake plus a separate physics registration, and the capture holds only
the first step. The remaining unknown in the container is the **per-type payload
codec**, and the route into it is the measurement technique that already settled
the record and fragment layers: hook the type's reader and log what it consumes.

**Method note.** Twice this session a model passed every check it was given and
was still wrong, because "consumes the body exactly" is necessary but not
sufficient. The fix each time was to stop validating the model against itself and
measure what the client actually does.
