# Decompilation backlog — everything still open

Paused 2026-10-02. This is the complete inventory of what remains for the
decompilation and data work, so any later session can resume without re-deriving
anything. The program itself (why, layers, rules) stays in
[DECOMP-PLAN.md](DECOMP-PLAN.md); tool procedure in
[DECOMPILATION.md](DECOMPILATION.md); measured PAK facts in
[PAK-FORMAT.md](PAK-FORMAT.md).

Legend: **[E]** has direct evidence · **[I]** inferred, not yet decisive ·
**[?]** unknown, no evidence either way.

---

## 0. Baseline — what is already done (do not redo)

| Done | Evidence |
| --- | --- |
| Code corpus, all 423,579 `.pdata` functions | 1,695 shards, 423,542 `ok` / **37 `fail`**, verified by set equality against `ranges.txt` (0 missing, 0 duplicates). `%LOCALAPPDATA%\Azoth\decomp\corpus\8654f01d324636d9` **[E]** |
| Toolchain installed and green | Ghidra 12.1.4 at `%USERPROFILE%\tools\ghidra_12.1.4_PUBLIC`; `peutil.py selftest` 6/6; `decomp.py --selftest` OK **[E]** |
| xref map built and cached | 280,594 targets, `lea r64,[rip+disp32]` only, `%LOCALAPPDATA%\Azoth\decomp\xrefmap.json` **[E]** |
| PAK container measured | 123 paks, 1,413,205 entries, full central-directory index in **6.1 s**. Method 0 = store (90,949), method 8 = raw deflate (583, verified byte-identical), method 15 = unknown (1,321,673, 93.5%) **[E]** |
| World renders, local player possessed | RESOLVED 2026-10-02, fresh PID 25952 / session 232 — `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` **[E]** |
| Gate mechanism read from pseudocode | `FUN_146929DF0` / `FUN_146764CD0` chain, thread-local option store; `research/derived/decomp/gate-chain.c`, landmarks in `symbols.json` **[E]** |

---

## 1. Code corpus debt

| # | Item | Notes |
| --- | --- | --- |
| 1.1 | **Retry the 37 `fail` rows with a higher `--timeout`** | Grouped in shards 401/402 and a few others; messages are 55–87 bytes. Their `.idx` rows must be removed first or `corpus.py` skips them. Genuinely low value (37 of 423,579) but it is the last untidy edge of a "complete" claim. |
| 1.2 | **The corpus has no names, types or strings** | It was imported with `-noanalysis`, so every function is `FUN_<va>` and `.rdata` addresses do not appear. This is the single biggest usability gap: the dump is a search index, not readable source. Naming is the real long-term work, one system at a time. |
| 1.3 | **No PDB exists** for this build | Confirmed: `failed to locate PDB file`. Names will never come from symbols, only from analysis + the reflection registry. **[E]** |
| 1.4 | **Verify the corpus pseudocode is correct** | It is decompiler output with no ground truth on any function except the handful that were hand-checked. Treat as a map, not a specification. |

## 2. Data layer (PAK)

| # | Item | Notes |
| --- | --- | --- |
| 2.1 | **Decode Oodle (method 15–19)** — the top blocker | Identified 2026-10-02: the codec is **RAD Oodle, statically linked**, and 15–19 are one family. Named API: `oo2::OodleLZ_Decompress` `0x1479f0820`, `oo2::OodleLZ_Compress` `0x1479efea0`. Dispatch: `0x147174570` → `0x147142e50`; codec id from `0x147132390`; **512 KiB** in-place ring (`0x80000`) with 256 KiB Oodle block granularity, not a 64 KiB prefix. Open: (a) which Oodle codec is method 15 — read the 32 registry bytes at `0x1485ee7f0`; (b) the 8-byte header; (c) the token grammar (Oodle's bit-packed `newLZ`). |
| 2.1b | **Call the client's own decoder** | Cheapest real route to extraction: `OodleLZ_Decompress` is at a known VA inside the exe, so a local harness can load the image and call it. No reimplementation, nothing to distribute. Not attempted. |
| 2.2 | **Write the PAK index tool** | Reads central directories only; 6.1 s measured. Writes `{path, pak, ext, csize, usize, crc32, method}`, plus a committed summary of counts per extension and method. Must not run while a corpus dump writes. Unblocked. |
| 2.3 | **Find the localization packs** | A named DECOMP-PLAN deliverable. Do it from the 2.2 index; no separate scan needed. |
| 2.4 | **Prove the edit path** | Extract one file, change it, repack with method 8 or 0, launch the private client, see the change. **Not blocked by 2.1** — repacking never needs the method-15 reader. This is the cheapest concrete proof that content mods are possible. |
| 2.5 | **Format readers for content we intend to edit** | Cry level (`level.pak`), DataSheet (`*.datasheet`), dynamicslice, LyShine `.uicanvas`, localization string tables. Each needs its own format work; extract one file at a time rather than unpacking the tree. |
| 2.6 | Unverified from ANALYSIS.md | Prior counts (`GameData` 18,034; `DataStrm` 19,331; `SharedDataStrm` 65,491; part1 65,199) were not reproduced in the measured index run. Reconcile when the index tool lands. **[?]** |

## 3. Named loaders (DECOMP-PLAN work order step 3)

None are named yet. Each is "find the loader function from the corpus + strings + xrefs, record it in `research/derived/symbols.json` with `va`, `what`, `found_by`".

| # | Loader | Why |
| --- | --- | --- |
| 3.1 | DataSheet (`NewWorldDataSheet`) | Quests, NPCs, items, weapons. |
| 3.2 | dynamicslice | Entities and prefabs. |
| 3.3 | LyShine canvas | UI. |
| 3.4 | Localization string table | Text and languages. |
| 3.5 | Slayer Script | Abilities and combat behaviour. |
| 3.6 | Coatlicue terrain | Terrain streaming, if a zone is ever changed. |

**Blocker shared by all six:** the corpus has no strings, symbols or types. You can
still navigate it well — data references render as `&UNK_<va>` / `_DAT_<va>` and
jump tables are visible — but you must obtain a string's VA with `peutil.py str`
first, because the text itself is not typed. See §9.

## 4. Protocol corpus — deadline 2027-01-31

The only workstream with a hard deadline: after Amazon's shutdown the plaintext
source is gone. DECOMP-PLAN lists six themes required from official sessions.

**Status from the 2026-09-06 captures ([SESSIONS.md](SESSIONS.md)):**

| Theme | Status |
| --- | --- |
| Combat and abilities | Partial — `CameraLockComponentClientFacet` ×6, one `SlayerScriptComponent` unknown-entity CRC. No ability payload. |
| Inventory / equip / storage | **Missing** — zero Game.log lines; lives in DTLS. |
| Gather to depletion | Partial — 7 distinct nodes, 9 `GatheringInterrupted`; completion is not logged. |
| Death and respawn | Partial — `entity was destroyed` notices only; **no Death/Respawn string**. |
| Quest accept / advance / complete | **Missing** — not recorded. |
| Expedition enter (`LevelInfoChanged`, `RepAddress` change) | **Missing** — no dungeon `LevelInfoChanged`, needs a group or a solo instance. |

**A contradiction in the plan that must be resolved by a human decision.** The
plan asks for these "from live official sessions, one theme each, passive capture
only while EAC is active". But the capture kit is documented to see only IPs,
ports, sizes and timing on official traffic — **never bodies** — because official
HTTPS and DTLS are encrypted and the TLS is pinned. So passive official capture
**cannot** produce a message-level protocol corpus. **[E]**

Two ways out, both real:

1. **Capture from our own server.** The gateway already stores exact request and
   response bodies, and the world server sees post-DTLS plaintext (plus
   `AZOTH_LOG_RAW=1` for the encrypted carrier). Now that the world renders
   (§0), the client exercises the real paths against Azoth and those bodies are
   captured in the clear. This is the only route that yields bodies, and it is
   **now unblocked**.
2. **Keep official captures only for the metadata they can give** (addresses,
   ports, timing, and the *existence* of message families), never as a body
   source.

Recommendation: drop the framing of "six official-theme captures" and restate the
goal as "drive each system against our own server and capture the bodies". The
official deadline then applies to the **encrypted carrier metadata** and to the
Game.log facts, not to bodies.

## 5. World / simulation frontier that needs RE

The black frame is solved; this is the measured new frontier (2026-10-02, session
232). Detail in [WORLD-INVESTIGATION.md](WORLD-INVESTIGATION.md).

| # | Item | Notes |
| --- | --- | --- |
| 5.1 | **No movement** — constant ~21 msg/s regardless of input, with the window focused | The player renders as a replica with no input-driven local controller bound. Needs a static + live trace of the local input → controller path. Reuses §7. |
| 5.2 | **No inventory** — 23 `RMIDispatch` errors, all `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems` | The replay addresses storage facets that do not exist locally. Decide: create the facets in the replay, or teach the server to answer. |
| 5.3 | **26 remote-player slice warnings** (`Couldn't get Transform component on the slice!`) | Other players' actors, not the local one. A slice-shape problem. |
| 5.4 | **`State(InGame) is timeout` still fires every 30 s** | `scripts/patch-timeout-watchdog.py` patches a different site than the one reporting. Find the reporting site. |
| 5.5 | Replay completeness | Once 5.1–5.4 close, the replay still only covers what the capture contains. Systems never exercised in a capture have no data. |

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

Tooling for it exists: `research/tools/reversing/analyze.py` and
`ghidra/DisableSlowAnalyzers.java` (disables the decompiler-based analyzers).

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
| **git-bash mangles `cmd.exe /c ...`** | MSYS rewrites `/c` into a path and the command silently never runs. Python `subprocess` with a list is safe; the `tools/reversing` scripts use it. |
| **git-bash `tar` cannot read zip** | Use `/c/Windows/System32/tar.exe -xf` (bsdtar). |
| `services/world` needs `pyOpenSSL` | The one deliberate non-stdlib dependency (stdlib `ssl` has no DTLS). |
| Private runtime has the DTLS disk patch applied | `scripts/patch-dtls-disk.py`, sha256 `537403d4…`. Restore with `python scripts/patch-dtls-disk.py restore` when finished. The official Steam exe is untouched. |
| Caddy can hang after a restart | Verify `https://d1w0bfy6smo4d1.cloudfront.net/prod/game/getlogininfo/jwt/omni` through `:443` returns 200 before blaming the world server. |
| `observed-endpoints.json` churns | Rewritten live by the gateway, so it is permanently dirty in `git status`. Commit it deliberately after a session (`python az.py doc`), not mid-run. |
| Concurrent writers | Two writers sharing one worktree make the diff non-atomic and make review targets go stale. Use separate worktrees. |

---

## 10. Suggested order

1. **PAK index tool (2.2)** — 6 seconds, unblocked, and it is the prerequisite for 2.3 and everything in 6.
2. **Prove the edit path (2.4)** — repack with method 8; does not need the codec. Cheapest proof content mods work.
3. **Resolve the capture-strategy contradiction (§4)** — a human decision, and the only item with a deadline. The world rendering again makes the "capture from our own server" route viable now.
4. **Movement (5.1)** — the next world frontier, and it is what makes the simulation feel real.
5. **Oodle decode (2.1b)** — call the client's own `OodleLZ_Decompress` at `0x1479f0820` from a local harness. It is the cheapest real route to reading existing content, and it needs no reimplementation. Do 2.1's registry read first to get the codec id.
6. **Named loaders (3.x)** — follows from whichever content system we actually edit first.
7. **Inventory (5.2)**, then 5.3/5.4.
8. **New weapon (6.2)** and the rest of §6 — last, and only once the pipeline is proven.
