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
- [ ] T4 — **Prove the edit path**: extract one file, change it, repack with
      method 8 or 0, launch the private client, see the change. Repacking does not
      depend on T2; only reading existing method-15 entries does.

## Not blocked here

Reading and editing terrain (`CoatlicueStrm`), vegetation, shader binaries, and
every `levels/*/level.pak` works today with stdlib `zipfile`.

## Evidence log

| When | What |
| --- | --- |
| 2026-10-01 | All 123 paks are standard ZIPs; full entry index measured in 6.1 s (central directories only). Method histogram: 0 → 90,949, 8 → 583, 15 → 1,321,673. |
| 2026-10-01 | Method 8 proven to be raw deflate: `terrain/terrain.dat` (36,072,416 B) decoded byte-identical to `zipfile.read()`. |
| 2026-10-01 | Method 15 unidentified after exhaustive black-box testing against the `config/game.xml` ground-truth pair; public Lumberyard `ZipFileFormat.h` stops at method 14. Needs the client's code. |
