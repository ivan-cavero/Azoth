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
| Function-range index for 423,579 `.pdata` functions, **rebuilt fresh 2026-10-06** under `reverse/builds/8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e/corpus/` (build 1.400.6031.6004151) | Pass 1 (60 s timeout): 423,540 `ok` / 39 `fail`. Pass 2 (300 s): +4 → 423,544 `ok`. Pass 3 (600 s + `setMaxPayloadMBytes` ladder, see §9 "payload ladder"): +20 → 423,564 `ok`. Pass 4 (parent-range walk-back from `int3` padding for the mid-function fragments, `shard-169502`): **423,579 ranges accounted for — 423,542 `ok` / 37 `fail`** (see §1.1a; the earlier "0 `fail`" here was wrong). Range accounting is not proof that all pseudocode is correct, and it is `.pdata`-scoped (§1.1b). |
| Method 15 = Oodle **Kraken**, decoded exactly by a third-party reader | 31/31 exact CRC matches (ground-truth pair + 30 random entries across 5 paks + the `.dds` header exception), 0.7 s, no process access. Methods 16–19 do not exist in the install. [PAK-FORMAT.md §4f](PAK-FORMAT.md) **[E] (2026-10-05)** |
| Toolchain installed and green | Rebuilt 2026-10-06 on this machine (Ghidra 12.1.4, JDK 25.0.4.1, checksum-pinned under `.azoth/tools/`). **All selftests green**: decomp selftest, PAK selftest 5/5 (incl. wheel-crasher regression via vendored DLL), PAK-index selftest (1,413,205 entries, 121 paks, methods {0: 90949, 8: 583, 15: 1321673} — matches the 2026-10-01 baseline exactly), namer selftest (710,766 refs / 423,579 functions). **kraken.dll build on machines without g++**: MSVC works — `vcvars64.bat && cl /nologo /LD /O2 /MT /EHsc /I<vendor/ooz> kraken.cpp ooz_shim.cpp /Fe:.azoth/tools/ooz/kraken.dll` (export is `__declspec(dllexport)` in the shim, no define needed). |
| xref map built and cached | **Rebuilt 2026-10-06**: 280,594 targets (`lea r64,[rip+disp32]` only) at `reverse/builds/8654f01d…c8e/xrefmap.json`, matching the historical count exactly. Spot-checked: `publicStatusCode` @`0x1483c0988` xrefs `0x144f54d63` inside `big_parser` (ground truth). Query: `python ef.py re xref xrefs --needle <text>`. Note: `xrefmap.py dump` crashes without `--lo/--hi` (cosmetic `int(None)` traceback). |
| PAK container measured | 123 paks, 1,413,205 entries, full central-directory index in **6.1 s**. Method 0 = store (90,949), method 8 = raw deflate (583, verified byte-identical), method 15 = unknown (1,321,673, 93.5%) **[E]** |
| World renders, local player possessed | RESOLVED 2026-10-02, fresh PID 25952 / session 232 — `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` **[E]** |
| Gate mechanism read from pseudocode | `FUN_146929DF0` / `FUN_146764CD0` chain, thread-local option store; local generated `gate-chain.c`, landmarks in `research/atlas/client-functions.json` **[E]** |
| Phase campaign rebuilt and grown 2026-10-06 | All 6 flow phases decompiled clean: 21 manifest seeds + 13 first-order E8 callers + **10 second-order callers = 44/44 done, 0 failed** under `reverse/builds/8654f01d…c8e/campaign/`. Growth persisted to the committed manifest (`research/atlas/decomp-campaign.json`). **Convergence measured**: sweeping all 44 done functions' E8 callers yielded only 10 new unique functions at order 2 — the direct call graph around the phase seeds is saturated; further growth must come from new anchors (strings, reflection, vtables), not more caller sweeps. Cross-check: expanding from the unreliable replication gate re-derived `FUN_146929df0` (the confirmed gate-chain) — campaign and atlas agree. Deliberate skip: `0x1416bcba0` (1,571 direct callers, generic utility). Also fixed: `campaign.py` ledger never advanced past `pending` (see §9). **Ivan's standing decision: past runtime struct claims (`+0xAA8`-style) are leads, not facts — the phase-by-phase game walk re-verifies them (§9).** |

---

## 1. Code corpus debt

| # | Item | Notes |
| --- | --- | --- |
| 1.1 | ~~**Rebuild the new corpus and retry its failures**~~ **DONE 2026-10-06 — full coverage** | Fresh corpus under `reverse/builds/8654f01d…c8e/corpus/`: **423,579/423,579 ranges `ok`, 0 `fail`** after four passes (60 s → 300 s → 600 s + payload ladder → parent-range walk-back). Retry ledger: `shard-169500` (pass 2), `shard-169501` (pass 3), `shard-169502` (pass 4). The payload-ladder and fragment-parent techniques are recorded in §9 so the next build reuses them instead of re-deriving. |
| 1.1a | **CORRECTION 2026-10-09 — "0 `fail`" here contradicted §9; the real number is 37** | Read from the authoritative `corpus/shards/*.idx` (423,579 entries, 423,579 unique VAs, matching `ranges.txt` exactly): **423,542 `ok` / 37 `fail`**. §9 already states this correctly (the `.idx` accumulates 37 cumulative `fail` rows while `progress.json` describes only its last pass); this row is corrected so the two do not disagree. List them with `grep -h 'status=fail' -A 1 corpus/shards/*.c`. "Every range was attempted" is true; "every range decompiled" is not. **[E]** |
| 1.1a-note | **The 37 failures, by cause (re-read 2026-10-09 from the shards, not from `corpus.log`)** | **20× `process: timeout`** · **10× `Cannot properly adjust input varnodes`** (mid-function `.pdata` fragments; the parent-range walk-back in §9 does not recover every one) · **6× `Response buffer size exceeded`** (the 50 MB `DecompileOptions` payload cap, despite the ladder) · **1× `Trying to construct memory range beyond end of address space: ram`**. Timeouts are the **dominant** cause, so "not timeouts" is exactly backwards. `corpus.log` is cumulative across all four passes, so counting causes there inflates them (it shows 64× `Unable to resolve constructor` and 2× `Could not follow disassembly flow`, and **none** of those 66 are in the final 37): count causes from the shard files, which hold the last write. |
| 1.1b | **The corpus covers `.pdata` only — 13,943 leaf functions in `.text` are outside it** | Scan of `.text` for `48 8D 05 rel32 C3` (`lea rax,[rip+X]; ret`) + `CC CC` padding: 13,943 standalone leaf functions, **0 of them in `ranges.txt`**. These carry no unwind info, so `.pdata` omits them and the corpus never touches them. The typed dispatcher's type accessors are this exact shape, which is why the movement type path was invisible to the corpus. Reach them with `decomp.py --range`; `--target` refuses. Coverage claims in this repo are `.pdata`-scoped. **[E]** |
| 1.2 | **Name the functions Azoth needs; leave the rest anonymous until needed** | `namer.py` builds string-reference candidates in `research/derived/namer-candidates.json`; **regenerated 2026-10-06: 21 candidates from 13 seeds** against the fresh corpus-refs index. Pipeline validated: seed `datasheet` re-derives `0x145c34dd0`, the already-confirmed `datasheet_path_joiner`. Confirm candidates by reading the function or checking an independent signal. |
| 1.3 | **No PDB exists** for this build | Confirmed: `failed to locate PDB file`. Names come from analysis, reflection metadata, and other binary evidence rather than symbols shipped with the client. **[E]** |
| 1.4 | **Verify the corpus pseudocode is correct** | It is decompiler output with no ground truth on any function except the handful that were hand-checked. Treat as a map, not a specification. |
| 1.5 | **Add types only where a required code path needs them** | Resolve string, container, and object layouts from callers, constructors, and runtime evidence. Do not apply guessed type overlays to the full corpus. |

## 2. Data layer (PAK)

| # | Item | Notes |
| --- | --- | --- |
| 2.1 | ~~Decode Oodle (method 15)~~ **RESOLVED 2026-10-05 at the reader level** | Method 15 is Oodle **Kraken** and `pakread.py` decodes it exactly via the vendored ooz DLL (2.1c): 31/31 CRC-exact + the wheel-crasher regression case ([PAK-FORMAT.md §4f](PAK-FORMAT.md)). The codec-id registry mapping in `FUN_147132390` is [I] informational only; the 8-byte prefix is the Oodle stream itself; the token grammar never needed reimplementing. Static chain (dispatch VAs, 512 KiB ring) remains valid evidence. |
| 2.1b | ~~Call the client's own decoder~~ **superseded by the DLL** | The vendored ooz `kraken.dll` handles every payload family measured, including the multi-quantum 17 MB heightmap and the restart-boundary layouts. Keep only as a last-resort comparison if a future maintenance exe ships payloads ooz rejects. |
| 2.1c | ~~Vendor the Oodle reader~~ **DONE 2026-10-05 (with a real bug fixed)** | `pakread.py` + `vendor/ooz/` (kraken.cpp/kraken.h from powzix/ooz @ `1d1051ad`, zlib license, vendored unmodified; `ooz_shim.cpp` adds the 64-byte dst padding ooz needs — the pip wheel `kraken-decompressor` allocates exactly dst_len and heap-corrupts, 0xc0000374, on some payloads; first reproduction `SharedDataStrm-part6.pak::javelindata_perks.datasheet`). DLL compiled into `.azoth/tools/ooz/`; fallback venv is `.azoth/venvs/kraken/`. Selftest includes the crasher as a regression. Command: `python ef.py re pak-read selftest`. |
| 2.2 | ~~Write the PAK index tool~~ **DONE 2026-10-05, re-validated 2026-10-06** | `reverse/tools/pakindex.py` — sqlite index at `.azoth/cache/pak-index/pakindex.db` (gitignored) + tracked summary `research/derived/pak-summary.json` (top extensions: meta 317k, dynamicslice 249k, dds 99k, cgf 87k). Build 37.2 s after the 2026-10-06 re-download (1,413,205 entries / 123 paks — identical to the 19.4 s pre-deletion build). Selftest pins the 2026-10-01 baseline. |
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
| **Campaign ledger never advanced — FIXED 2026-10-06** | `campaign.py pending()` returned shallow copies (`{**t, "key": key}`) and `cmd_run` marked `done`/`failed` on the copy, so `save_state` persisted unchanged statuses and every batch re-decompiled the same pending targets. Fixed by writing outcomes into `state["phases"][name]["targets"][t["key"]]`. Verified: `login` target `0x1474ea680` (`getlogininfo_request_builder`) now shows `done=1`. |
| **Campaign growth was not durable — FIXED 2026-10-09** | `cmd_add`/`cmd_expand` — the documented growth path — wrote only to `STATE` (`campaign-state.json`), which lives under the ignored per-build workspace. The grown target list therefore died with the machine: a 2026-10-07/08 session grew its local list to 108 targets while the committed manifest still declared 45, and the 63 extras existed only on that host's disk. `MANIFEST` is the phase map that `campaign init` replays, so growth has to land there. Fixed by adding `persist_spec_to_manifest()`, which appends the declarative spec (`symbol`/`va`/`callers_of`/`range` + note) to the committed manifest, deduped on the declarative key rather than the note. Verified: `add` 45→46, a repeat add is a no-op, and `init` from a deleted state reproduces the grown set from the manifest alone. Note the `.c` output stays per-build and ignored by design; only the phase map is committed. |
| **Payload ladder for "Response buffer size exceeded" — FIXED 2026-10-06** | Ghidra 12.1.4's `DecompileOptions` caps decompiler output at 50 MB (`SUGGESTED_MAX_PAYLOAD_BYTES`); 13 corpus functions legitimately exceed it. `DecompileCorpus.java openIfc()` now walks a payload ladder (2048→1024→512→50 MB). Traps measured: `getOptions()` returns null until an explicit `setOptions` (NPE); the native process **rejects out-of-range values**, which makes `openProgram` return false and every decompile then fails silently with an empty message — hence the ladder with an always-valid 50 MB fallback. Also: `MAXMEM`-style env vars don't apply to this limit. |
| **Mid-function `.pdata` fragments ("Cannot properly adjust input varnodes") — technique** | Some `.pdata` entries are funclet/region fragments whose code assumes the parent's stack frame; decompiling them standalone fails. Verified with Capstone (e.g. `0x146c2a81f` starts mid-epilogue). Recovery: walk back from the fragment start to the nearest ≥8-byte `int3` padding run to find the parent's real start, then decompile that full range (`.azoth/tmp/build-parents.py` pattern; results in `shard-169502`). Decompile the parent, not the fragment. |
| **Runtime-derived struct facts are [I], pending a phase re-walk — Ivan's call 2026-10-06** | Past probe findings of the form "+0xAA8 is X" (field writers, struct layouts, timing) are treated as **leads, not settled facts** until re-verified during the phase-by-phase game walk. The static corpus is the base; every phase re-derives its own evidence before building on an old offset claim. Do not add new layers on top of an unverified offset. |
| **The Steam `assets` directory was emptied 2026-10-06 (~16:57)** | Someone deleted the 79 top-level PAKs (~76 GB) from `C:\...\New World\assets\`. The exe survived byte-identical (SHA-256 re-verified `8654f01d…c8e` after the re-download), so all build-scoped analysis stayed valid, but the PAK work needed a full re-download. Rule: the Steam install is read-only for every agent and tool; never delete or move game files; verify the exe hash before resuming build-scoped work after any install event. |
| **PowerShell locale trap** | `Get-Process ... .TotalProcessorTime` formatted with `{0:N1}` prints `1.623,0` = **1623.0 s**, easily misread as 1.6 s, which produced a false "the process is hung" conclusion. Format with an invariant culture or print raw seconds. |
| **git-bash mangles `cmd.exe /c ...`** | MSYS rewrites `/c` into a path and the command silently never runs. Python `subprocess` with a list is safe; the `reverse/tools` scripts use it. |
| **git-bash `tar` cannot read zip** | Use `/c/Windows/System32/tar.exe -xf` (bsdtar). |
| `services/world` needs `pyOpenSSL` | The one deliberate non-stdlib dependency (stdlib `ssl` has no DTLS). |
| Private runtime has the DTLS disk patch applied | `scripts/patch-dtls-disk.py`, sha256 `537403d4…`. Restore with `python scripts/patch-dtls-disk.py restore` when finished. The official Steam exe is untouched. |
| Caddy can hang after a restart | Verify `https://d1w0bfy6smo4d1.cloudfront.net/prod/game/getlogininfo/jwt/omni` through `:443` returns 200 before blaming the world server. |
| `observed-endpoints.json` churns | Rewritten live by the gateway, so it is permanently dirty in `git status`. Commit it deliberately after a session (`python ef.py doc`), not mid-run. |
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

---

## 12. Movement: the named target list and its wire types (2026-10-09)

The movement frontier is a **missing server→client message family**, not a client
bug. `SERVER-CONTRACT.md` records the asymmetry: the client broadcasts its
local-player state on channel 1 (10,736 records measured live, **10,718 of them
flags 0x20 = UNRELIABLE**, dominant size 119 B) and the server answers only on
channels 0 and 3. In the capture there is **no movement message in the R
direction at all** (0x635 is W-only, 5 records).

### What was missing until now

`JAVELIN-MESSAGE-GUIDS.md` maps names to AZ type GUIDs, but the wire carries an
**index** into the per-build type table, not the GUID. Without that index a GUID
cannot be turned into bytes, so the family was *named but not addressable*.
`private-client/runtime/typeindex.json` is that table (`typeIndex`, 7052 GUIDs,
position = wire type). Resolved and recorded in `client-functions.json`
(`movement_family_wire_types`):

| Message | wire |
| --- | --- |
| `MoveAnActorMsg` | `0x54` |
| `MoveActorMsg` | `0x2c6` |
| `MoveActorToHubMsg` | `0x2ce` |
| `ProcessDeferredMovementRequestsMsg` | `0x2d3` |
| `StartMovementCommunicationMsg` | `0x2d6` |
| `MovementTimeoutMsg` | `0x2e0` |
| `AckMovementMsg` | `0x2e3` |
| `CommitMovementMsg` | `0x2e4` |
| `AbortMovementMsg` | `0x2e9` |
| `CheckMovementStatusMsg` | `0x2eb` |
| `ReceivePlayerPositionClientMsg` | `0x1078` |
| `CancelMovementMsg` | `0x14de` |

Independent corroboration: the family lands in a **contiguous block 0x2c6-0x2eb**,
which is what a family registered together looks like. Round-trip checked
(`0x2ce` -> `0A8F6818915C47009C33463862BBE5F0` = `MoveActorToHubMsg`).

### What is still missing: the body encoding

A correct type with an invented body is useless — the client discards it, exactly
as the recorded `AZOTH_REPLAY_CHANNEL1_ECHO` negative result showed. The
serializer `FUN_146a55850` (candidate name, descriptor-adjacent to
`StartMovementCommunicationMsg`) writes to a stream through vtable `+0x40` and
calls the field writers `FUN_140876cd0` / `FUN_1408770e0` / `FUN_146167320`. It
gives **struct offsets**, not wire layout:

```
+0x08 (0x10B)  +0x18 (4B)  +0x1c (0x10B)  +0x2c (0x10B)
+0x40 (4B)     +0x44 (4B)  +0x48          +0x50
```

### Negative results — do not repeat

- The descriptor-table pointers for `StartMovementCommunicationMsg` are **type
  comparators, not handlers**. `FUN_141756db0` compares an incoming GUID against
  two singletons and returns 1 on match — the same shape as
  `typed_dispatcher_type_compare` (`FUN_146158ba0`). `FUN_141752700` and
  `FUN_141754050` are singleton accessors (`lea rax,[singleton]; ret`).
- Wire `0x635` is **not** in the movement family. Its GUID is
  `01346CCD785E448DA4294B281972B1D7`, unnamed in the 156-type registry, and it sits
  outside the 0x2c6-0x2eb block. It is the state stream, not movement.
- "The client is blocked because we never ACK channel 1" is **ruled out**: 99.8%
  of channel-1 records are unreliable (flags 0x20) and expect no ACK.

### Next step (cheapest first)

1. **Validate the type empirically before deriving the body.** The `inject` lever
   exists for exactly this: write `services/world/inject.hex` and the live session
   sends it on the next tick (`scripts/world-inject.py`, `PeerSession.maybe_inject`).
   Send a `StartMovementCommunicationMsg` (`0x2d6`) with the correct type and a
   minimal body against a live session and watch `Game.log` for a decode warning.
   A clean accept proves the type and the framing; that is worth more than a
   derived-but-unverified body.
2. Decompile the client's **reader** for that type (the counterpart of
   `FUN_146a55850`) and read the field order it consumes.
3. Only then drive the family: `StartMovementCommunicationMsg` -> position
   updates -> `AckMovementMsg` / `CommitMovementMsg`.

Prerequisite already in place: the server now has an authoritative tick
(`PeerSession.tick`, `TICK_HZ`), so movement can be emitted on the server's own
clock instead of in proportion to inbound traffic.

### 12.1 Entity replication: measured, and the exact rejection (2026-10-09)

The mechanism already existed and is **not** a naive loop: `maybe_state_stream`
selects only the captured **tail** (`0x08` with `seq >= STATE_STREAM_MIN_SEQ`,
0xA0) so it never replays the 46 KB spawn bundles, and rewrites the bundle's
sequence byte to continue above the client's high-water
(`STATE_STREAM_REWRITE_SEQ`, offset 4). Tested live with
`AZOTH_REPLAY_STATE_STREAM=1` on top of the recommended block.

**Result: the old negative result does not reproduce.** The earlier failure
(758 `skipping ReceiveStateBundle`, ClientContext lost) came from re-sending the
bundles with their ORIGINAL seqs, which the client rejected as already-seen. With
the seq rewrite, `skipping ReceiveStateBundle` is **1** (pre-spawn) instead of
758, `clientContext == nullptr` is **1**, and the session held **6.8 minutes**
with `transportError` 0, `disconnected from REP` 0, `Cleanup` 0. The seq rewrite
is what made the difference.

**But the bundles are still not applied.** 32 bundles are rejected:

```
MessageEnvelope: Failed to unmarshal MessageEnvelope::m_message.
  {"unmarshalError":"ValidationError","messageTypeId":"8A40AEC2AE074F929BF378FC0CC94FDF"}
ClientSDK: Failed to unmarshal message: num_bytes=78, type=8A40AEC2AE074F929BF378FC0CC94FDF
```

`8A40AEC2AE074F929BF378FC0CC94FDF` is wire type `0x08` (verified against
`typeindex.json`). The failures are **one loop pass exactly**: first at
18:17:57, last at 18:19:00, 32 of them, one per 2 s period, then they stop. The
first pass (original captured seqs) is accepted; the looped pass (rewritten seqs)
is not.

**The likely cause is already written in the code and was only half-applied.**
The comment at `rep.py:248` records the client's acceptance test as TWO
conditions:

```
FUN_14643e7b0 accepts an unreliable replication message only when
  msg.clientContextInstanceId == port[+0x80]   AND
  *(u64*)(msg+0x28) > port[+0x78]  (m_lastUnreliableReplicationSeq)
```

`STATE_STREAM_REWRITE_SEQ` satisfies only the second. If the first is also
enforced on the looped body, the fix is to rewrite the bundle's
`clientContextInstanceId` field as well — not to invent a body.

**Next step:** locate `clientContextInstanceId` inside the `0x08` body (the
validator reads it via `FUN_1406d97b0` = `return msg+0x28` for the seq, and
`FUN_1406c10a0` = `return byte [msg+0x30]`, so the neighbouring offsets are the
place to look), rewrite it alongside the seq, and re-measure the failure count.
Success criterion: the `Failed to unmarshal` count for type
`8A40AEC2AE074F929BF378FC0CC94FDF` goes to **0** across a full loop pass.

### 12.2 The seq rewrite is the sole difference — and it is what fails (2026-10-09)

Isolated the failure to one byte. In the capture, the `0x08` tail bodies
(seq 0xa0..0xb0) are byte-identical in their first 8 bytes except offset 4:

```
seq=0xa0  body[0:8]=0001080125010101   body[4]=25
seq=0xb0  body[0:8]=0001080135010101   body[4]=35
```

So `body[4]` is a monotonic counter 0x25..0x35 (37..53) — the GridMate
unreliable replication counter the code comments describe. The rewrite position
is therefore correct. What is NOT established is that the client accepts a
rewritten value: every captured value is **< 0x40**, while
`STATE_STREAM_SEQ_FLOOR` makes the loop start at **0x80**.

The first pass through the tail (original bodies, original seqs, delivered by the
replay) is **accepted**. Every bundle from the looped pass is **rejected** with
`ValidationError` — 32 failures, one per 2 s period, covering exactly one loop
(18:17:57 -> 18:19:00, 63 s), then they stop. The only difference between the
accepted and rejected copies of the same bundle is byte 4.

Two candidate explanations, and the A/B that separates them:

1. **The value range is invalid** — the field may be a packed bitfield where
   bit 0x80 means something, so starting the counter at 0x80 corrupts it.
   Test: `AZOTH_REPLAY_STATE_STREAM_SEQ_FLOOR=0x36` (continue from the captured
   maximum instead of jumping to 0x80).
2. **The rewrite itself is wrong for this field** — `body[4]` may not be the seq
   the validator compares, in which case the counter is being corrupted while the
   real high-water check still fails. Test: `AZOTH_REPLAY_STATE_STREAM_SEQ=0`
   (rewrite OFF) and compare the failure count.

Both are one env var on an otherwise unchanged run:

```powershell
$env:AZOTH_REPLAY_STATE_STREAM='1'
$env:AZOTH_REPLAY_STATE_STREAM_SEQ_FLOOR='0x36'   # A/B: vs 0x80 (default)
```

Success criterion for either: the `Failed to unmarshal` count for type
`8A40AEC2AE074F929BF378FC0CC94FDF` goes to **0** across a full loop pass. Note the
error is a *deserialization* (`ValidationError`) failure, not a dedup rejection,
so explanation 1 is the better fit: a dedup rejection would not fail unmarshal.

### 12.3 RESOLVED: the seq rewrite was corrupting the bundles (2026-10-09)

The three-run A/B settles 12.2, and the answer is neither of the two candidates
listed there:

| Run | `Failed to unmarshal` | Session |
| --- | --- | --- |
| `SEQ_FLOOR=0x80` (old default) | 32 | 6.8 min |
| `SEQ_FLOOR=0x36` | 32 | 7.3 min |
| **`REWRITE=OFF`** | **0** | **7.4 min**, 207 bundles, `transportError` 0, `disconnect` 0 |

**CORRECTION 2026-10-09 (later the same night): "any write to `body[4]`" is wrong.**
`body[4]` is not a raw byte, it is a **prefix varint** (see `javelin/varint.py` and
`JAVELIN-PROTOCOL.md` section 2d), and the old code did
`body[STATE_STREAM_SEQ_OFFSET] = self.state_stream_seq & 0xFF` with
`STATE_STREAM_SEQ_FLOOR` defaulting to **`0x80`**. `0x80` has its high bit set, so
writing it turns a **one-byte varint into a two-byte one** and shifts the entire
fragment list. That is the `Failed to unmarshal ... ValidationError`: a length
misalignment, not a magic byte. The `FLOOR=0x36` run fails for a different reason —
those re-applied records are the capture's own, and re-applying them is not
idempotent client-side.

**Second correction: with the rewrite OFF the bundles are not delivered, they are
dropped.** Their counter is at or below the client's high-water, so the replication
gate (`FUN_14643e7b0`, see `replication_unreliable_gate_20261003`) discards them
*before* any deserialization. The earlier "207 bundles with zero deserialization
failures" therefore does not show that they applied — they were never parsed.

**Fix applied:** the rewrite now re-encodes the varint through the verified parser
(`javelin.bundle.with_replication_seq`), which rebuilds the bundle so a wider value
cannot misalign the fragments. It stays default **off** because whether re-applying
a captured record is idempotent client-side is still unproven and needs a live run.

**Test:** `test_wire_seq_rewrite_is_off_by_default` pins the default, and
`test_wire_seq_is_rewritten_when_explicitly_enabled` keeps the old behaviour
covered behind the explicit flag.

**What this means for entity replication:** the transport path works — bundles are
delivered, deserialize cleanly, and the session is stable for 7+ minutes with
replication on. What is NOT yet established is that the client *applies* them:
`skipping ReceiveStateBundle` is 1, so they are not being skipped, but no
independent signal has been read that shows world state advancing. Next step is a
state signal, not more transport work.
