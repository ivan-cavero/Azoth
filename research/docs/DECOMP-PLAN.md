# Decompilation plan — full client, native emulator, modifiable game

Persistent program for the frozen New World client. If a session dies, start
here, then follow the resume steps at the bottom. Tool mechanics live in
[DECOMPILATION.md](DECOMPILATION.md). The world-entry stall is a separate
track: [WORLD-INVESTIGATION.md](WORLD-INVESTIGATION.md).

Last updated: 2026-10-01.

## Objective

Own this build of the client well enough to:

- Run a private server that feels like the official game. The frozen client
  stays the renderer. Azoth is the simulation. "Native" means the client
  loads its own PAKs and receives the replicas it already knows how to apply.
- Go past the official servers on density and responsiveness once the
  protocol is closed. That work lives in the Azoth world server
  ([ROADMAP.md](../../docs/ROADMAP.md)), after spawn is real.
- Change the game's content: backgrounds, intros, text, languages, UI,
  quests, items, and new weapons (this game's "classes"). Content edits are
  PAK edits plus a server that uses the same ids and CRCs. Behavior changes
  that the data cannot express are made in the few client systems we name
  and, when we must ship a new binary behavior, recompile.

Amazon shipped no further seasons after Nighthaven. Servers go offline on
2027-01-31. A maintenance exe is still possible before that date. Until the
bytes change, every address below is stable.

## Reconstruction, ports, and mods

A game that has been decompiled into source which compiles again can be
rebuilt, ported, and modded at the source. That is what matching
decompilations have done for small titles: the C compiles back to the
original bytes, and from that tree people ship a native port or a source
mod. The sentence is true for a recompilable tree. It is the long-term end
state of this plan, reached per system, as we need to change that system.

For this client the same outcome splits three ways:

- **Content mods** (backgrounds, intros, text, languages, UI, quests,
  weapons) come from the PAK layer and a server that uses the same ids.
  The frozen client already loads those files.
- **A server that feels like the official game** is the protocol layer.
  This build is already a native Windows x64 game. The PC "port" exists.
  Azoth replaces the official servers, then improves density and rules.
- **A reconstructed client** (rebuild `NewWorld.exe`, then a native build
  for another OS or a replaced renderer) starts from the pseudocode corpus
  as a map. Recompilable C is written for the modules we actually change,
  beginning with the loaders and the platform edge. The bulk corpus does
  not compile, and a single matching pass over all 423579 functions is not
  a prerequisite for mods or for the private server.

## The build this plan is tied to

| | |
| --- | --- |
| Version string | `[RETAIL].Javelin.1.400.6031.6004151` |
| Compiled | 2026-03-21 |
| Engine | Amazon Lumberyard 1.12.0.1, game DLL name `Javelin` |
| exe sha256 | `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` |
| pdata functions | 423579 (zero-length entries dropped) |
| Image base | `0x140000000` |

If a maintenance client ships, hash the new exe. A different hash gets its
own corpus directory. Finish or archive the old one. Do not mix shards.

## Three layers

The C dump is layer 1. It does not, by itself, make the emulator or let us
edit a quest.

### 1. Code corpus (running)

Ghidra pseudocode of every `.pdata` function, one frozen build, outside the
repo so 400k files never land in git.

- Directory: `%LOCALAPPDATA%\Azoth\decomp\corpus\8654f01d324636d9\`
- Launcher: `python research/tools/reversing/corpus.py`
- Live counter: `progress.json` in that directory (`finished`, `ok`, `fail`,
  `rate_per_s`, `eta_s`, `status`).
- Shards: `shards/shard-NNNNNN.c` plus a sibling `.idx`
  (`start`, `status`, `bytes`, `shard`). A function begins with
  `########## <start>-<end> status=ok name=FUN_... ##########`.
  The range is the `.pdata` range, end exclusive.
- Project used read-only: `Azoth\decomp\ghproj` program `azoth` /
  `NewWorld.exe`. The dump must be the only Ghidra process on that project.
  `decomp.py --serve` cannot run beside it.
- Resume is the same command. Completed VAs are skipped from the `.idx`
  files. A crash loses at most the open shard (250 functions).

On 2026-10-01 the run was past ~88k functions, 10 threads, a handful of
`status=fail` rows, ETA on the order of an hour at ~90/s. Trust
`progress.json` over this paragraph. `status=complete` is the gate for
layer 2. Failures stay in the shards and can be retried later with a higher
`--timeout`. They do not block the inventory.

This corpus is the search index. Names are `FUN_<va>` until we rename a
system on purpose. Readable source is produced only for the loaders and
game systems we actually edit (layer 3 of the work order below). A
byte-identical matching decompilation of all 423579 functions is not the
deliverable.

### 2. Data corpus (next, after the C dump)

Backgrounds, intros, text, languages, UI, quests, and items live in the
Steam `assets` tree, not in the exe. The client already has the world. The
server says `LevelInfoChanged` (`NewWorld_VitaeEterna`) and then replicates
actors.

Do not unpack every PAK. Build an index: path, pak, extension, uncompressed
size. Extract a file only when we are about to read or edit it. The install
is tens of GB (`DataStrm*`, `SharedDataStrm*`, `VegetationStrm*`,
`shadersbin_d3d12.pak`, `levels\`). Running that index while the corpus is
still writing will fight it for disk. Wait until `progress.json` says
`complete`.

| Change we want | Where it lives | Format |
| --- | --- | --- |
| Open world | `assets/levels/newworld_vitaeeterna/level.pak` | Cry level |
| Expeditions, raids, trials, OPR, arenas | `assets/levels/nw_dungeon_*`, `nw_raid_*`, `nw_trial_*`, `nw_opr_*`, `nw_arena_*` | Cry level |
| Backgrounds, intros, menu | `frontend`, `frontendv2*`, `main_menu`, `nw_frontend_nighthaven`, `ftue_v2`, `ftue_v2_cc` | Cry level + textures |
| Terrain | `CoatlicueStrm.pak`, `coatgen/` in SharedDataStrm | dynamicslices per chunk |
| Entities, prefabs | `*.dynamicslice` in SharedDataStrm | Lumberyard slices |
| Quests, NPCs, items, weapons | `sharedassets/springboardentitites/datatables/*.datasheet` | binary DataSheet |
| UI | `lyshineui/` in DataStrm | `.uicanvas` + `.dds` |
| Text and languages | localization tables inside the PAKs (exact pack is part of the index) | string tables |
| Meshes, anims | `.cgf` / `.caf` in DataStrm and SharedDataStrm | Cry |
| VFX | `GameData.pak` | mtl, xml particles |

A new "class" is a weapon plus a skill tree plus Slayer Script plus anims
plus icons plus the combat component replicated by the server. There is no
class enum to extend.

Edit path, once the index exists:

1. Extract the one file.
2. Change it (clone an existing slice or datasheet; keep ids coherent).
3. Repack so the client sees it through `PaksList.lst`.
4. Teach the server the same ids and CRCs.
5. Spawn with `Cmd_NewProxy`.

Proof that the path works is one edited string, one UI canvas, and one
quest, each visible in the private client. A new zone with its own terrain
is an art project on top of Coatlicue, later.

Engine code we do not have to rediscover from scratch: Lumberyard 1.12
(GridMate, slices, pak layout) is public. The game layer on top (Javelin,
NewWorldDataSheet, Slayer Script, LyShine canvases, Coatlicue) is ours to
name from the corpus.

### 3. Protocol corpus (deadline 2027-01-31)

The emulator matches official behavior only for messages we have seen in
plaintext. After shutdown that source is gone. The exe dump is not on this
deadline. Captures are.

Still required from live official sessions, one theme each, passive capture
only while EAC is active ([EAC.md](EAC.md), [CAPTURE.md](CAPTURE.md)):

- Combat and abilities (Slayer Script on the wire)
- Inventory, equip, storage
- Gather to depletion
- Death and respawn
- Quest accept, advance, complete
- Expedition or other instance enter (`LevelInfoChanged`, whether
  `RepAddress` changes)

Each captured message lands in the atlas
(`research/atlas/`) and, when it is normative, in
[REP-PROTOCOL.md](REP-PROTOCOL.md). Guessed fields stay marked
`"evidence": "guessed"`.

## Work order

1. **Finish the code corpus.** Let the current process run. Do not start a
   second Ghidra on `ghproj`. Do not scan the PAK tree until
   `status=complete`.
2. **PAK index.** Classify every entry by extension and top directory.
   Write the index under `%LOCALAPPDATA%\Azoth\` (or `research/derived/`,
   gitignored), with a short committed summary of counts per type. Find the
   localization packs in that index.
3. **Name the loaders.** From the corpus plus strings and xrefs, record in
   `research/derived/symbols.json` the functions that load DataSheets,
   dynamicslices, LyShine canvases, localization, and Slayer Script. One
   system at a time. Confirmed wire keys go to the atlas the day they are
   confirmed.
4. **Take the protocol captures** in the list above before 2027-01-31.
   This can run on days the corpus and the index are not saturating the
   machine. It cannot wait until the end.
5. **Edit pipeline.** Extract, modify, repack, launch the private client,
   confirm the string, the canvas, and the quest. Then a new weapon datasheet
   whose server component uses the same ids.
6. **Widen the server** system by system (movement, combat, inventory,
   quests, instances) against those captures. Spawn and the black InGame
   view stay on the world-investigation track and are not postponed until
   the corpus is pretty.

## Rules that keep the weeks additive

- A fact that is only in chat does not exist. Function: `symbols.json`
  (`va`, `what`, `found_by`). Wire: `research/atlas/`. Levers spotted in
  passing: `research/atlas/levers.md`.
- The corpus is regenerable. Do not commit shards, `progress.json`, or PAK
  extracts.
- One fresh `NewWorld.exe` per world A/B. A dead `ClientContext` makes every
  later measurement lie. See [WORLD-DEBUGGING.md](WORLD-DEBUGGING.md).
- No ReadProcessMemory and no Frida while EAC is active.
- Pseudocode answers "where is the loader". It is not a patch. Client
  behavior changes stay in the launcher's pattern patches until a named
  module is actually recompiled.

## Resume after a cut session

1. Read this file, then `progress.json` in the corpus directory.
2. If `status` is `decompile` or `disassemble` and `corpus.pid` is alive,
   leave it alone.
3. If the pid is dead and `status` is not `complete`, run
   `python research/tools/reversing/corpus.py` from the repo root. It
   resumes. If it refuses because a live pid still holds `ghproj`, stop
   that process first.
4. If `status` is `complete`, start the PAK index (layer 2). Do not redo
   the dump.
5. Check the capture list above against `research/docs/SESSIONS.md` and the
   atlas before spending a session on a system we already recorded.
6. World-entry work continues from
   [WORLD-INVESTIGATION.md](WORLD-INVESTIGATION.md), in parallel, on a
   machine state that is not in the middle of the dump.
