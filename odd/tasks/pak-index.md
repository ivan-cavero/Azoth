# pak-index — layer 2: PAK index and the method-15 codec

Second workstream of [DECOMP-PLAN.md](../../research/docs/DECOMP-PLAN.md) (work order
step 2). Measured facts and the reproduction recipe live in
[PAK-FORMAT.md](../../research/docs/PAK-FORMAT.md); this file tracks the tasks.

## Why this feature exists

Content edits (text, languages, UI, quests, items, weapons) are PAK edits plus a
server that uses the same ids. Layer 1 is the code corpus; this layer is the data
corpus. It is independent of the layer-1 dump except for disk contention.

## Tasks

- [ ] T1 — **PAK index tool.** Walk `assets/**/*.pak`, read central directories
      only, write `{path, pak, ext, csize, usize, crc32, method}` per entry under
      `%LOCALAPPDATA%\Azoth\pakindex\` (gitignored), plus a committed summary of
      counts per extension and method. Measured cost: 123 paks, 1,413,205 entries,
      **6.1 s**. Must not run while the layer-1 corpus is writing.
- [ ] T2 — **Crack method 15** (1,321,673 entries, 93.5%). Blocked on reading the
      client's decompressor dispatch; needs the layer-1 corpus (or a freed Ghidra
      project) to decompile the function that maps `nMethod` to a codec. Negative
      results and ruled-out codecs are listed in PAK-FORMAT.md so this is not
      re-derived.
- [ ] T3 — **Find the localization packs** in the index (localization tables are a
      named DECOMP-PLAN deliverable).
- [x] T4 — **Prove the edit path**: extract one file, change it, repack with
      method 8 or 0, launch the private client, see the change. Repacking does not
      depend on T2; only reading existing method-15 entries does.
      **2026-10-05: 3 of 4 steps proven** by `pakwrite.py` (extract via Kraken →
      string edit asserted exactly-once → one-entry method-8 patch pak →
      round-trip verified through the raw-deflate reader; selftest green). Demo
      artifact: `research/derived/pak-edit/npcmisc_patch.pak` (regenerable). The
      fourth step (PaksList.lst + private-client launch) is client-owned — the
      exact commands are printed by `pakwrite.py make`.

## Not blocked here

Reading and editing terrain (`CoatlicueStrm`), vegetation, shader binaries, and
every `levels/*/level.pak` works today with stdlib `zipfile`.

## Evidence log

| When | What |
| --- | --- |
| 2026-10-01 | All 123 paks are standard ZIPs; full entry index measured in 6.1 s (central directories only). Method histogram: 0 → 90,949, 8 → 583, 15 → 1,321,673. |
| 2026-10-01 | Method 8 proven to be raw deflate: `terrain/terrain.dat` (36,072,416 B) decoded byte-identical to `zipfile.read()`. |
| 2026-10-01 | Method 15 unidentified after exhaustive black-box testing against the `config/game.xml` ground-truth pair; public Lumberyard `ZipFileFormat.h` stops at method 14. Needs the client's code. |
| 2026-10-05 | **T2 RESOLVED at the reader level** (DECOMP-BACKLOG 2.1): method 15 = Oodle **Kraken**; `pakread.py` decodes it exactly via the vendored `kraken-decompressor` wheel (bootstrapped once into `%LOCALAPPDATA%\Azoth\tools\krakenv`, gitignored). Validation 31/31 exact CRCs incl. the `.dds` header exception; methods 16–19 do not exist in the install. Static chain in PAK-FORMAT §4b stays as evidence. |
| 2026-10-05 | **T1 DONE**: `pakindex.py` (sqlite index under `%LOCALAPPDATA%\Azoth\pakindex\`, tracked summary `research/derived/pak-summary.json`). Selftest OK against the 2026-10-01 baseline. Build took 19.4 s (first run; central dirs only). Correction captured: `SharedDataStrm-part12/13.pak` are 22-byte bare EOCDs, not 0 bytes (PAK-FORMAT corrected). Localization packs located: `localization/<lang>/*.loc.xml` in `DataStrm*` (T3 target — next: extract one and read the format). |
| 2026-10-05 | **T3 DONE**: localization format read end-to-end (`pakread.py`): `<resources><string key="…">text</string>` XML, Cry-style. First extraction: `DataStrm-part3.pak::localization/es-es/0c_01_npcmisc.loc.xml` (794 B, `01_CaptainThorpe_title` → "Corsario inglés"). |
| 2026-10-05 | **T4 3/4**: `pakwrite.py` proven (extract → edit → method-8 patch pak → round-trip). Demo `npcmisc_patch.pak` written to `research/derived/pak-edit/`. Client launch step left to the world session's owner; `PaksList.lst` priority (first line wins for duplicate paths) is the claim to verify with that launch. |
| 2026-10-05 | **T5 started: `.datasheet` format probed** (`javelindata_perks_deprecated.datasheet`, 97,517 B). Measured so far: header `u32 version=18`, two u32 checksums, `u32 7`, `u32 28`, `u32 1`, `u32 5769` (= string-table size in bytes — verified: `len(file) - 0x16664 == 5769`); a 38-entry `[name_hash u32][row_byte_offset u32][type u32]` column index (0x5c..0x224, offsets 37→789, types 1/2, count matches u32[10]=38); a sparse u32 region (mostly 0 / 611 / 816 = string-table offsets pointing at the NUL before each string, string starts at offset+1, 0 = empty); then a mixed region (u32 string offsets AND raw numbers — at 0x4004 values exceed the string table); NUL-terminated string table with column names first (`Output`, `ItemPerks_Deprecated`, `PerkData`, `PerkID`, `PerkType`, `ConditionEvent`, `ItemClass`, …) then data values (perk/equip strings, `LyShineUI\Images\…`). NOT yet decoded: exact row stride/variable-length record layout and where u32[9]=91,688 fits. Probe file: `research/derived/decomp/perks_deprecated.datasheet` (regenerable with pakread.py). |
| 2026-10-05 | **Decoder hardened**: the `kraken-decompressor` wheel heap-corrupts (0xc0000374) on some payloads — root cause: ooz may write up to 64 B past dst, wheel allocates exactly dst_len. Fix: vendored ooz `kraken.dll` with a padded ctypes shim (`vendor/ooz/`, zlib license); wheel demoted to subprocess-isolated fallback. Regression case added to `pakread.py` selftest (`javelindata_perks.datasheet`). Multi-quantum/restart-boundary payload validated (17 MB heightmap). |
| 2026-10-05 | **T5 DONE — datasheet format CLOSED**: `datasheet.py` reads real rows. Measured: header version 18, u32[6] = string-table size (byte-exact on 4 files), column directory `[CRC32(lowercase(name))][name_off][type]` (1=str, 2=f32, 3=bool), 8-byte cells (str: string-off/0; float: 0/LE-f32; bool: 0/0|1), offsets point AT the first char (0 = empty). Validated: perks 659 rows (unique PerkIDs), perks_deprecated 300, perks_infix 14, perks_gems 442 — all 38 columns, same layout. Earlier confusion resolved: offsets are NOT variable-length records; the file is columnar-cells + string table. Also measured: .uicanvas/.dynamicslice = AZ ObjectStream binary v3 (u32 0 + BE u32 version 3 + element tree; root class 75651658-8663-478D-9090-2432DFCAFA44) — documented in symbols.json `uicanvas_binary_layout`. |
