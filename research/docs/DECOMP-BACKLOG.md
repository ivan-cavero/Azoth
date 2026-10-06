# Decompilation backlog — everything still open

Updated 2026-10-05 (external research pass + Oodle decode validated; see §2.1 and §11).
This records measured results and open work. Local corpora from older machines
are historical evidence only and must not be resumed. The program itself (why,
layers, rules) stays in
[DECOMP-PLAN.md](DECOMP-PLAN.md); tool procedure in
[DECOMPILATION.md](DECOMPILATION.md); measured PAK facts in
[PAK-FORMAT.md](PAK-FORMAT.md).

Legend: **[E]** has direct evidence · **[I]** inferred, not yet decisive ·
**[?]** unknown, no evidence either way.

---

## 0. Baseline — what is already done (do not redo)

| Done | Evidence |
| --- | --- |
| Function-range index for 423,579 `.pdata` functions | Historical result: 1,695 shards; `.idx` covered every range exactly once, with 423,542 `ok` / 37 cumulative `fail`. The old user-local output is not an input to new work. Rebuilds belong under ignored `reverse/builds/<full-sha256>/corpus/`. Range accounting is not proof that all pseudocode is correct or successful. |
| Method 15 = Oodle **Kraken**, decoded exactly by a third-party reader | 31/31 exact CRC matches (ground-truth pair + 30 random entries across 5 paks + the `.dds` header exception), 0.7 s, no process access. Methods 16–19 do not exist in the install. [PAK-FORMAT.md §4f](PAK-FORMAT.md) **[E] (2026-10-05)** |
| Toolchain installed and green | Historical result: Ghidra 12.1.4 and the RE self-checks passed **[E]**. New installs are checksum-pinned under `.azoth/tools/`. |
| xref map built and cached | Historical result: 280,594 targets, `lea r64,[rip+disp32]` only. Rebuild into the current hash-scoped workspace; do not copy the old per-user cache. |
| PAK container measured | 123 paks, 1,413,205 entries, full central-directory index in **6.1 s**. Method 0 = store (90,949), method 8 = raw deflate (583, verified byte-identical), method 15 = unknown (1,321,673, 93.5%) **[E]** |
| World renders, local player possessed | RESOLVED 2026-10-02, fresh PID 25952 / session 232 — `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` **[E]** |
| Gate mechanism read from pseudocode | `FUN_146929DF0` / `FUN_146764CD0` chain, thread-local option store; local generated `gate-chain.c`, landmarks in `research/atlas/client-functions.json` **[E]** |

---

## 1. Code corpus debt

| # | Item | Notes |
| --- | --- | --- |
| 1.1 | **Rebuild the new corpus and retry its failures** | The old 37 cumulative failures are historical and must not be edited or resumed. A fresh run must emit its own per-build range ledger, successful decompilation count, and retry queue before anyone calls that build complete. |
| 1.2 | **Name the functions Azoth needs; leave the rest anonymous until needed** | `namer.py` builds string-reference candidates in `research/derived/namer-candidates.json`; the first DataSheet, dynamicslice, canvas, and component-path names are already in `research/atlas/client-functions.json`. Confirm candidates by reading the function or checking an independent signal. |
| 1.3 | **No PDB exists** for this build | Confirmed: `failed to locate PDB file`. Names come from analysis, reflection metadata, and other binary evidence rather than symbols shipped with the client. **[E]** |
| 1.4 | **Verify the corpus pseudocode is correct** | It is decompiler output with no ground truth on any function except the handful that were hand-checked. Treat as a map, not a specification. |
| 1.5 | **Add types only where a required code path needs them** | Resolve string, container, and object layouts from callers, constructors, and runtime evidence. Do not apply guessed type overlays to the full corpus. |

## 2. Data layer (PAK)

| # | Item | Notes |
| --- | --- | --- |
| 2.1 | ~~Decode Oodle (method 15)~~ **RESOLVED 2026-10-05 at the reader level** | Method 15 is Oodle **Kraken** and `pakread.py` decodes it exactly via the vendored ooz DLL (2.1c): 31/31 CRC-exact + the wheel-crasher regression case ([PAK-FORMAT.md §4f](PAK-FORMAT.md)). The codec-id registry mapping in `FUN_147132390` is [I] informational only; the 8-byte prefix is the Oodle stream itself; the token grammar never needed reimplementing. Static chain (dispatch VAs, 512 KiB ring) remains valid evidence. |
| 2.1b | ~~Call the client's own decoder~~ **superseded by the DLL** | The vendored ooz `kraken.dll` handles every payload family measured, including the multi-quantum 17 MB heightmap and the restart-boundary layouts. Keep only as a last-resort comparison if a future maintenance exe ships payloads ooz rejects. |
| 2.1c | ~~Vendor the Oodle reader~~ **DONE 2026-10-05 (with a real bug fixed)** | `pakread.py` + `vendor/ooz/` (kraken.cpp/kraken.h from powzix/ooz @ `1d1051ad`, zlib license, vendored unmodified; `ooz_shim.cpp` adds the 64-byte dst padding ooz needs — the pip wheel `kraken-decompressor` allocates exactly dst_len and heap-corrupts, 0xc0000374, on some payloads; first reproduction `SharedDataStrm-part6.pak::javelindata_perks.datasheet`). DLL compiled into `.azoth/tools/ooz/`; fallback venv is `.azoth/venvs/kraken/`. Selftest includes the crasher as a regression. Command: `python az.py re pak-read selftest`. |
| 2.2 | ~~Write the PAK index tool~~ **DONE 2026-10-05** | `reverse/tools/pakindex.py` — sqlite index at `.azoth/cache/pak-index/pakindex.db` (gitignored) + tracked summary `research/derived/pak-summary.json` (top extensions: meta 317k, dynamicslice 249k, dds 99k, cgf 87k). Build 19.4 s. Selftest pins the 2026-10-01 baseline. |
| 2.3 | ~~Find the localization packs~~ **DONE 2026-10-05** | Via the 2.2 index: `localization/<lang>/` (en-us, es-es, es-mx, de-de, fr-fr, it-it, pl-pl, pt-br) across `DataStrm*` paks. Format: `<resources><string key=…>text</string>` XML (Cry localization), read end-to-end with `pakread.py`. |
| 2.4 | **Prove the edit path** — 3 of 4 steps done 2026-10-05 | `reverse/tools/pakwrite.py`: extract (Kraken) → edit (string replace, exactly-once asserted) → repack as a one-entry method-8 zip → verify round-trip through the raw-deflate reader. Selftest green; a real demo patch pak (`npcmisc_patch.pak`, `Corsario inglés` → `Corsario de Azoth`) at `research/derived/pak-edit/` (regenerable). **Remaining step is client-owned**: copy the patch pak into `<install>/Assets/`, add `Assets/npcmisc_patch.pak` as the FIRST `PaksList.lst` line (priority claim to verify with that one launch), launch the private client — owned by the world session / Ivan. |
| 2.5 | **Format readers — localization DONE, datasheet DONE, uicanvas/slice layout measured (2026-10-05)** | Localization: `<resources><string key=…>` XML, end-to-end. **DataSheet DONE**: `reverse/tools/datasheet.py` (stdlib, selftest 13/13 green) — header (version 18, string-table-size u32 verified = filelen−st_start), column directory `[CRC32(lowercase(name))][name_off][type 1=str|2=f32|3=bool]`, row grid of 8-byte cells (str: off+0/0; f32: 0/LE float; bool: 0/0|1), NUL-terminated string table. Validated on FOUR files: perks (38 cols/659 rows, PerkIDs unique), perks_deprecated (38/300), perks_infix (38/14), perks_gems (38/442). **uicanvas/dynamicslice container MEASURED** (`research/atlas/client-functions.json` `uicanvas_binary_layout`): AZ ObjectStream binary v3 — `[u32 0][u32 BE 3][element tree]`, root class 75651658-8663-478D-9090-2432DFCAFA44; readable with the public O3DE ObjectStream format. Cry level `.pak`: untouched. |
| 2.6 | Unverified from ANALYSIS.md — partially reconciled | The 2.2 index (`pak-summary.json`, `entries_per_pak`) is the authoritative source now; compare against ANALYSIS §9's old counts when touching that doc. **[?]** for the specific old numbers. |

## 3. Named loaders

The first names are confirmed and recorded in
`research/atlas/client-functions.json`. Map only the loaders needed by the
next feature, then continue the broader asset families when useful. Do not
redo the initial string/xref candidate pass.

| # | Loader | Why |
| --- | --- | --- |
| 3.1 | DataSheet (`NewWorldDataSheet`) | Quests, NPCs, items, weapons. First lead: `datasheet_path_joiner` `0x145c34dd0` (path normalization; confirmed 2026-10-05). File format probed (see 2.5). |
| 3.2 | dynamicslice | Entities and prefabs. First leads CONFIRMED 2026-10-05: `dynamicslice_path_suffix_check` `0x140774fe0` (paths stored without extension) and `lc_spawnslice_console_command` `0x14101b4b0` (client console spawn, prepends `slices/characters/`). |
| 3.3 | LyShine canvas | UI. First lead CONFIRMED 2026-10-05: `uicanvas_type_ctor` `0x14053aaa0` + `uicanvas_dynamicuicanvas_type_getters` (type ids {E48DDAC8…}/{A7A9AAE0…}, handler vtables 0x147f02fa8/0x147f02f18, asset object built by FUN_1406ec3a0). Binary layout measured (see 2.5). |
| 3.4 | Localization string table | Text and languages. DONE as a format (2.5); packs located via the index. |
| 3.5 | Slayer Script | Abilities and combat behaviour. |
| 3.6 | Coatlicue terrain | Terrain streaming, if a zone is ever changed. |

The corpus pseudocode uses anonymous `FUN_<va>` names and unresolved data
references such as `&UNK_<va>` / `_DAT_<va>`. `namer.py` turns string references
into candidates, but each candidate needs a checked function body or an
independent signal before it becomes a confirmed name. See §9.

## 4. Protocol corpus — deadline 2027-01-31

The only workstream with a hard deadline: after Amazon's shutdown the plaintext
source is gone. DECOMP-PLAN lists six themes; how they get captured is restated below.

**Status from the 2026-09-06 captures ([SESSIONS.md](SESSIONS.md)):**

| Theme | Status |
| --- | --- |
| Combat and abilities | Partial — `CameraLockComponentClientFacet` ×6, one `SlayerScriptComponent` unknown-entity CRC. No ability payload. |
| Inventory / equip / storage | **Missing** — zero Game.log lines; lives in DTLS. |
| Gather to depletion | Partial — 7 distinct nodes, 9 `GatheringInterrupted`; completion is not logged. |
| Death and respawn | Partial — `entity was destroyed` notices only; **no Death/Respawn string**. |
| Quest accept / advance / complete | **Missing** — not recorded. |
| Expedition enter (`LevelInfoChanged`, `RepAddress` change) | **Missing** — no dungeon `LevelInfoChanged`, needs a group or a solo instance. |

**Resolution of the capture-strategy contradiction (restated 2026-10-05, per this section's own
recommendation).** The framing "six official-theme captures" is dropped. The goal is now:
**drive each system against our own server and capture the bodies** — the gateway stores exact
HTTP bodies and the world server sees post-DTLS plaintext (plus `AZOTH_LOG_RAW=1` for the
encrypted carrier). Since the world renders (§0), this route is live. The 2027-01-31 deadline
still applies to what only official sessions can give: encrypted-carrier metadata (message
families, sizes, timing), Game.log facts, and the existence of systems we never exercise
locally. Official pcap stays a metadata source, never a body source.

### 4b. Entity→component creation path (the next system to name, measured 2026-10-05)

The system the movement agent needs creates a local entity's components when
state arrives. Measured facts are in `research/atlas/client-functions.json`;
fresh decompiles are in the ignored local `reverse/builds/<client-sha256>/` workspace:

- `FUN_141763b70` (**transform_spawner_chain_confirmed_20261005**): three queries of
  `param_1->vtable[+0x20](typeId {83482F97-84DA-4FD4-BF9E-7FE34C8E091F})`; each non-null
  answer spawns GameTransformComponent (+ m_worldTM/m_localTM/m_onNewParentKeepWorldTM/
  m_isStatic attached by name at +0x140/+0x180/+0x1b8/+0x201), then the Client facet, then the
  Server facet. The source that supplies a resolvable entity id is a lead; whether it maps to one
  specific wire record is not yet confirmed.
- `player_slice_content_20261005`: the player prefab has NO physics components at all —
  GameRigidBody*/CharacterPhysics/CharacterController are **absent** from
  `slices/player.dynamicslice` (all byte orders). They must arrive through a
  different entity/component path; the exact wire event remains unknown.
- The `.rdata` region at 0x1498a0000+ holding RuntimeFunction-format triples that reference the
  cluster is an **unwind-info copy, not a call table** (correction to the earlier note). No
  caller of `FUN_141761dd0`/`FUN_141763b70` exists in code or data found so far.
- `{83482F97…}` is loaded by six functions: `0x1404b5d80` (entity-iteration loop with vtables
  0x147f20740/0x147f233a8 — best publisher lead), `0x1407fb480`, `0x1425880d0`,
  `0x143d6e8a0`, `0x144389bb0`, `0x1444043b0`.

**Round 2 (2026-10-05, later):** type-id semantics pinned against public O3DE/Lumberyard
source — `{6383F1D3…}` = `AZ::EntityId` (AZ_TYPE_INFO in EntityId.h, 933x in the player
slice), `{75651658…}` = `AZ::Entity` (AZ_RTTI in Entity.h, root class of all slice/canvas
payloads). Trait descriptor layout in .rdata measured as `[name][~200 B][lowercase guid]`
(3-way verified: PersistenceSpawner, Aoi::GridActorClient, ClientMessagesTrait), so
`5ac34998-d340-4948-9cb3-7d5b2d24221d` = **ClientMessagesTrait** whose state object
`FUN_141542760` reads via `vtable[+0x30]`. The `NetBinding` namer seed landed
`netbinding_component_creators` (FUN_14628bea0/14628c100) — and the decisive cross-check:
**NetBindingComponent/NetBindingSystemComponent/NetBindingHandlerInterface are all ABSENT
from player.dynamicslice**, i.e. the player prefab ships without any net-binding component
and the server must supply the binding. Next concrete step for this thread: hook
`FUN_14628bea0`'s family (the NetBinding creators) on a private client to observe when a
net-bound entity is actually created, and compare against the wire state stream.

## 5. World / simulation frontier that needs RE

The black frame is solved; the live frontier is owned by the parallel session — read
[STATUS.md](../../STATUS.md) first (as of 2026-10-04: **the client self-reconnects ~5 s after
spawn and every reconnect destroys the `ClientContext`**, which explains the missing physics,
the dead WASD input and the cable growing until the next drop; measured symbols
`client_self_reconnect_kills_context_20261004`, `local_player_has_no_physics_20261004`,
`movement_input_ab_20261004`). This section keeps only the RE-shaped items that survive that
frontier; do not re-derive them from older notes.

| # | Item | Notes |
| --- | --- | --- |
| 5.1 | **Movement / local input controller** | Owned by the parallel world session. Input arrives (`GetRawInputData` → dispatcher `FUN_1449d5ec0`); the local player replica has 124 components and none of physics. Static + live trace of input → controller only becomes meaningful once the reconnect cuts stop. |
| 5.2 | **No inventory** — 23 `RMIDispatch` errors, all `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems` | The replay addresses storage facets that do not exist locally. Decide: create the facets in the replay, or teach the server to answer. |
| 5.3 | **26 remote-player slice warnings** (`Couldn't get Transform component on the slice!`) | Other players' actors, not the local one. A slice-shape problem. |
| 5.4 | **`State(InGame) is timeout` still fires every 30 s** | `services/launcher/runtime-tools/patch-timeout-watchdog.py` patches a different site than the one reporting. Find the reporting site. |
| 5.5 | Replay completeness | Once the reconnect cut closes, the replay still only covers what the capture contains. Systems never exercised in a capture have no data — this is why §4's own-server captures matter. |

## 6. Edit pipeline and content mods (the objective)

| # | Item | Notes |
| --- | --- | --- |
| 6.1 | Proof: one edited string, one UI canvas, one quest, each visible in the private client | The stated proof that content mods work. Depends on 2.2, 2.4, 2.5. |
| 6.2 | A new weapon ("class") end to end | Weapon + skill tree + Slayer Script + anims + icons + a combat component the server replicates. There is no class enum to extend. Long. |
| 6.3 | A new zone | An art project on top of Coatlicue. Later. |

## 7. Full Ghidra analysis — attempted twice, not completed

Needed because the corpus cannot answer "what references this address", which is
exactly what any vtable-reached function needs (the method-15 codec dispatch being
the live example).

| Attempt | Heap | Result |
| --- | --- | --- |
| 1 | 2 GB | Alive and working, but still in the early analyzers after 24 min, heavy GC (jstack: `ScalarOperandAnalyzer` → `CodeUnitDB.getBytes`) |
| 2 | 16 GB | Vanished after ~5–9 min: no error, no `hs_err`, no event-log entry, project 0 MB |

The cause of attempt 2's death is **[?] not established** and must not be guessed
at. The leading suspect is memory pressure on a 31 GB machine that simultaneously
runs a live game process — a suspect, not a fact.

Operational constraint to respect: this machine is shared with live game sessions
(each needing a fresh `NewWorld.exe`, the scarce resource). A multi-hour
multi-gigabyte analysis competes with them. Run it on an idle machine and watch
the first minutes.

Tooling for it exists: `reverse/tools/analyze.py` and
`ghidra/DisableSlowAnalyzers.java` (disables the decompiler-based analyzers).

**What the analyzed project would additionally buy (researched 2026-10-05; RTTI note
RETRACTED for game classes):** an early note here hoped Ghidra's PDB-less RTTI recovery
would hand us vtable-bound classes. Measured on 2026-10-05 by
`reverse/tools/rtti.py` (selftest OK): **this exe is compiled `/GR-` — the game
code has no vftable RTTI.** All 4,820 TypeDescriptors exist, but all 1,959 COLs (verified
two independent ways) belong to imported-CRT classes with zero vftable entries in `.text`.
RTTI recovery can only name STL/exception classes here. Game-class naming comes from the
AZ reflection registry + string references (DECOMP-BACKLOG 3.x).
Other cautions stand: demangler-adjacent analyzers dominate on symbol-rich binaries
([ghidra#2509](https://github.com/NationalSecurityAgency/ghidra/issues/2509)) and per-analyzer
timings are printed by headless runs ([ghidra#9298](https://github.com/NationalSecurityAgency/ghidra/discussions/9298)).
The remaining case for a full analysis is weaker now: call-graph discovery inside regions
where neither the reflection registry nor strings reach — decide per need, never as a
background job on a machine running game sessions.

## 8. Long-term: recompilable modules

Not started, and not a prerequisite for the private server or for mods. A matching
decompilation is reached **per module, as we need to change that system**,
beginning with the loaders and the platform edge. No build chain exists yet.

---

## 9. Tooling debts, environment quirks, and traps

| Item | Detail |
| --- | --- |
| **Heap env var bug — FIXED** | `decomp.py`, `corpus.py`, `analyze.py` set `MAXMEM`, which Ghidra 12.1.4 ignores; it reads `GHIDRA_MAXMEM` / `GHIDRA_HEADLESS_MAXMEM` (default 2G). All runs silently used 2 GB. Fixed and verified (`-Xmx16G` on a live JVM). The corpus completed anyway. |
| **The corpus DOES resolve data references — an earlier note in this file said otherwise** | Corrected 2026-10-02. References render as `&UNK_<va>` / `_DAT_<va>` **without** an `0x` prefix (712,257 of them); the earlier negative came from grepping for the bare hex VA. Jump tables also appear, as `IMAGE_DOS_HEADER_140000000.e_magic + *(uint*)(idx*4 + TABLE_VA)`. What the corpus genuinely lacks is the **strings themselves** (get a VA with `peutil.py str`, then search `&UNK_<va>`), symbols, and types. |
| **A search list is a claim** | The method-15 hunt concluded "custom LZ4 fork" from the absence of LZ4/LZHAM/ZSTD/snappy/LZO/Brotli names. **Oodle was never in the list** and `Oodle`/`oodle2` appear 34/35 times in the exe. Enumerate vendor families (RAD, Epic, LZ4, zlib, Zstd, LZFSE, LZO, Snappy, Brotli, LZHAM) before concluding from a negative. |
| **The `.rdata` interface tables are unproven** | The RVA tables at `0x149e15400+` and `0x149e46434+` holding the inflate function RVAs have **zero** references in every form checkable (no RIP-relative `lea` in a 64 KB window, no u32 RVA, no u64 pointer, and no corpus hit). Reading them as a codec interface table is **[I] unsupported**. `DECOMPILATION.md` already warns that a table with no xrefs may be decorative. Do not build on them. |
| **PowerShell locale trap** | `Get-Process ... .TotalProcessorTime` formatted with `{0:N1}` prints `1.623,0` = **1623.0 s**, easily misread as 1.6 s, which produced a false "the process is hung" conclusion. Format with an invariant culture or print raw seconds. |
| **git-bash mangles `cmd.exe /c ...`** | MSYS rewrites `/c` into a path and the command silently never runs. Python `subprocess` with a list is safe; the `reverse/tools` scripts use it. |
| **git-bash `tar` cannot read zip** | Use `/c/Windows/System32/tar.exe -xf` (bsdtar). |
| `services/world` needs `pyOpenSSL` | The one deliberate non-stdlib dependency (stdlib `ssl` has no DTLS). |
| Private runtime has the DTLS disk patch applied | `scripts/patch-dtls-disk.py`, sha256 `537403d4…`. Restore with `python scripts/patch-dtls-disk.py restore` when finished. The official Steam exe is untouched. |
| Caddy can hang after a restart | Verify `https://d1w0bfy6smo4d1.cloudfront.net/prod/game/getlogininfo/jwt/omni` through `:443` returns 200 before blaming the world server. |
| `observed-endpoints.json` churns | Rewritten live by the gateway, so it is permanently dirty in `git status`. Commit it deliberately after a session (`python az.py doc`), not mid-run. |
| Concurrent writers | Two writers sharing one worktree make the diff non-atomic and make review targets go stale. Use separate worktrees. |
| `.idx` rows vs `progress.json` | The `.idx` status fields are the resume gate and accumulate **across** runs (37 cumulative `fail` rows); `progress.json`'s `ok`/`fail` counters describe **only the last run** (`fail: 12` on 2026-10-01). When claiming "the corpus is complete", cite both, and trust the `.idx` for what will actually be skipped. |
| A pip-decoded finding needs a vendored tool | The 2026-10-05 Oodle validation ran in a disposable venv with `kraken-decompressor` (a C-extension wheel). Until 2.1c vendors it (or an `ooz` binary) under `research/tools/`, the finding reproduces but is not yet a repo tool. Do not add the pip dependency to `services/` — repo rule. |

---

## 10. Suggested order

1. **Vendor the Oodle reader (2.1c)** — the codec question is answered (§2.1 / [PAK-FORMAT.md §4f](PAK-FORMAT.md)); turn it into `reverse/tools/` code with a selftest (decode ground-truth pair → CRC match). First command is written in 2.1c.
2. **PAK index tool (2.2)** — 6 seconds, unblocked, prerequisite for 2.3 and everything in 6. Can land together with 2.1c in one tool.
3. **Prove the edit path (2.4)** — extract (Kraken), change, repack with method 8. Cheapest proof content mods work; extraction is no longer a blocker.
4. **Resolve the §4 capture plan into scheduled sessions** — drive each system against our own server and capture bodies (restated 2026-10-05). The only workstream with a deadline.
5. **Movement (5.1)** — owned by the parallel world session; unblocks only after the 2026-10-04 reconnect cut closes.
6. **Named loaders (3.x)** — corpus navigation + RTTI recovery (see §7) once we edit the first content system.
7. **Inventory (5.2)**, then 5.3/5.4.
8. **Analyzed Ghidra project (§7)** — only on an idle machine; the RTTI payoff makes it more valuable than before, but it never outranks a live session.
9. **New weapon (6.2)** and the rest of §6 — last, and only once the pipeline is proven.

## 11. External research findings (2026-10-05) — sources and what applies

Primary-source survey of the topics in this backlog, each marked with what applies to a
~180 MB MSVC x64 binary with no PDB. Items are horizon-tagged: **[A]** unblocks the emulator
now, **[B]** builds the corpus/protocol base, **[C]** future private-client modification.

| Topic | Finding (source, date) | Applies to Azoth as |
| --- | --- | --- |
| Oodle readers | `kraken-decompressor` (github.com/domdfcoding/kraken-decompressor, PyPI, C++ port of the ooz-family Kraken decoder, checked 2026-10-05); `ooz` (github.com/powzix/ooz, zlib license, decodes Kraken/Mermaid/Selkie/Leviathan/BitKnit/LZNA); `oozextract` (lib.rs/crates/oozextract, Rust). RAD's own docs (radgametools.com/oodlecompressors.htm) confirm Kraken/Mermaid/Selkie are one family. | **[A]** Validated 31/31 on this install (§2.1). Vendor one as a research tool. |
| Diffing builds (when a maintenance exe ships) | **BinExport** is a first-party Ghidra extension (github.com/google/binexport) feeding **BinDiff** (github.com/google/bindiff — free for non-commercial use, Ghidra supported as backend). **Diaphora** (github.com/joxeankoret/diaphora) is IDA/radare2-only — not our path. **Ghidra Function ID** computes full/specific function hashes and matches them against signature databases (ghidradocs.com FunctionID help) — suitable when compiled function bytes are unchanged, exactly our frozen-build case. **Ghidra Version Tracking** exists but is a GUI-heavy session workflow ([Version Tracking Intro](https://ghidradocs.com/9.1.1_PUBLIC/help/VersionTracking/help/topics/VersionTrackingPlugin/Version_Tracking_Intro.html)). | **[B]** First line for us is cheaper than all of these: our own anchors — `peutil.py str` + cached `xrefmap` + `bytepat.py` re-derivation, plus `research/atlas/client-functions.json` re-validation on the new hash (the DTLS site was already byte-identical across 1.365→1.400). Adopt BinExport+BinDiff only if whole-build diffing is ever needed; keep the client registry as the portability contract. |
| C++ naming without PDB | Ghidra's RTTI recovery works PDB-less (in-box `RecoverClassesFromRTTIScript` / `RTTIWindowsClassRecoverer`; DeepWiki overview "C++ Class Recovery from RTTI"). MSVC `std::string` layout for struct typing: 32 B SSO (union {char* ptr; char buf[16]}, size, capacity) ([Raymond Chen's comparison](https://devblogs.microsoft.com/oldnewthing/20240510-00/?p=109742)). | **[B]** Run RTTI recovery after any successful full analysis (§7). Typing the reflection-registry strings as MSVC strings in `decomp.py`'s helper is a cheap incremental win — no full analysis needed for that. |
| Ghidra analysis cost on huge binaries | Demangler-adjacent analyzers dominate on symbol-rich binaries ([ghidra#2509](https://github.com/NationalSecurityAgency/ghidra/issues/2509)); headless prints per-analyzer timings, use them to prune ([ghidra#9298](https://github.com/NationalSecurityAgency/ghidra/discussions/9298)); a stuck analyzer can hang headless timeouts ([ghidra#4296](https://github.com/NationalSecurityAgency/ghidra/issues/4296)) — "Non-Returning Functions - Discovered" is a known offender. | **[B]** Refines §7: when re-running `analyze.py`, log per-analyzer times and disable candidates by measurement, not folklore. |
| Lumberyard public source | `aws/lumberyard` (archived, full source; `dev/Code/Framework/GridMate/` is the MIT-licensed GridMate reference behind Javelin REP). | **[A/B]** Name map and wire reference. Every borrowed name must be marked "public relative, not verified in this exe" until the VA is confirmed here — same rule as first-light VAs. |
| Emulator prior art | EQEmu (docs.eqemu.dev) — 20+ years of from-scratch EQ server: opcode maps, zone/authority split, DB-driven content; the general pattern "capture packet families → opcode table → per-system handlers" is the shape §4 wants. L2R (github.com/l2r-dev/l2r) — modern Rust ECS MMO emulator. Generic tick/interest-management/lag-comp guides (generalistprogrammer.com 2025; sourcegame.net #37) match what ANALYSIS.md §5.4 already prescribes. | **[A]** Nothing new architecturally: our ANALYSIS.md §5.4 plan (server authority, fixed tick, cell AOI, unreliable movement) is the same shape as the successful emulators. The transferable lesson is EQEmu's discipline: every packet family documented with opcode + fields + evidence, exactly our atlas rule. |
| Reusable client modules | Matching-decomp practice (decomp.dev projects; jamesfmackenzie.com 2026 explainer): matching = byte-identical when recompiled with the original compiler; projects proceed per-module and treat the rest as a call-map. | **[C]** Confirms DECOMP-PLAN's "per system, as we need to change it" and §8: no whole-exe recompile goal, no build chain until a named module must change behavior. |
