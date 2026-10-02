# PAK container format — measured facts

Layer 2 of [DECOMP-PLAN.md](DECOMP-PLAN.md) (the data corpus). Everything here was
measured against the frozen install, not inferred.

| | |
| --- | --- |
| Install | `<Steam>/steamapps/common/New World/assets` |
| Paks | 123 (`assets/*.pak` + `assets/levels/*/level.pak`) |
| Entries | 1,413,205 total |
| On-disk size | 71 GB |
| Full index cost | **6.1 s** — only the ZIP central directories are read, never the payloads |

## 1. The container is a standard ZIP

Every `.pak` is a plain ZIP: local headers `PK\x03\x04`, central directory,
EOCD `PK\x05\x06`, no archive comment, no ZIP64. Python's stdlib `zipfile` opens
all 123 of them and lists names, sizes, and CRC-32 without help.

This makes the *index* cheap: one central-directory read per pak (a few MB at the
tail of each file) gives path, pak, extension, compressed size, uncompressed
size, and CRC-32 for all 1.4M entries. No payload byte has to be touched.

`ANALYSIS.md` says the PAKs "can be listed and extracted with any ZIP tool". That
is true for listing and for methods 0 and 8, and **false for extraction in
general**: see method 15.

## 2. Compression methods actually present

| Method | Meaning | Entries | Where |
| --- | --- | --- | --- |
| `0` | store | 90,949 | `CoatlicueStrm`, `VegetationStrm*`, `shadersbin_d3d11/d3d12`, `shadercachestartup`, several `levels/*/level.pak`, and the mixed `SharedDataStrm` parts |
| `8` | raw deflate | 583 | **only** `levels/*/level.pak` |
| `15`–`19` | **RAD Oodle** (one family; 15 is 93.5% of the install) | 1,321,673 for method 15 alone | all `DataStrm*`, `SharedDataStrm*`, `Engine.pak`, `GameData.pak` |

`zipfile` raises `NotImplementedError` ("That compression method is not
supported") on every method-15 entry. The index does not need to decompress, so
the index is unaffected; reading or editing content is.

Other container facts worth keeping:

- `SharedDataStrm-part12.pak` and `SharedDataStrm-part13.pak` are **0 bytes**.
- `SharedDataStrm-part1/2/3/8/9/10.pak` hold exactly 65535 entries: the packer
  rolls a new part at the ZIP 16-bit entry limit.
- Method 0 and method 8 entries are readable today with stdlib `zipfile`.

## 3. Method 8 = raw deflate, verified end to end

`levels/newworld_vitaeeterna/level.pak:terrain/terrain.dat` (compressed
123,987 → 36,072,416 bytes) decodes with `zlib.decompressobj(-15)` (raw deflate,
no zlib wrapper) to bytes **identical** to `zipfile.read()`. The same manual
decode from the local header offset matched `zipfile` exactly, which also
validates our header-offset arithmetic.

This matches Lumberyard's `ICryPak.h` comment: method 8 is stored "without
wrapping ... without waiting for compression method byte, as this is the way
it's stored into zip file".

## 4. Method 15 is RAD Oodle (methods 15–19 are one family)

Evidence, all from `Engine.pak:config/game.xml` (method 15, 1,161 → 7,046 bytes).
The same file exists loose at `assets/Config/Game.xml`, so we have exact ground
truth: sizes and CRC-32 match, and a brute-force decode can be checked by
equality with the plaintext.

**Read §4b first if you only read one part: the codec is RAD Oodle, statically
linked, and an earlier revision of this file wrongly concluded it was a custom
LZ4 variant with a 64 KiB prefix dictionary.**

### 4a. There is a header, and it encodes the compressed size twice

731 method-15 entries in `Engine.pak`. Across them:

| Relation | Holds |
| --- | --- |
| `data[0:2] == 8c 06` and `data[2] == 0` | 704 / 731 |
| `BE16(data[3:5]) == csize - 6` | 688 / 731 |
| `BE16(data[6:8]) == csize - 8` | 635 / 731 |

`data[5]` is not a constant: `0x88` ×584, `0x80` ×84, `0x89` ×9, `0x81` ×7,
`0x30` ×34, `0x20` ×6, `0x00` ×4, `0x51` ×2, `0x40` ×1.

So the true header length is at most 8 bytes, it carries the compressed size in
two big-endian 16-bit fields two bytes apart, and the packer does not always use
the same shape (`.dds` texture entries are among the exceptions — e.g.
`engineassets/animated/watervolume.dds` starts `8c 06 03`). The three relations
holding ~90% rather than 100% is itself a finding: **the header is not a fixed
record format**, so do not model it as one.

### 4b. The codec is RAD Oodle, statically linked

**This section was wrong before 2026-10-02 and is corrected here.** The payload is
not LZ4 and the history is not a 64 KiB prefix. The client statically links RAD
Oodle, and methods 15–19 are its family.

Strings in `NewWorld.exe` (verified by counting bytes, ASCII, not UTF-16):
`Oodle` ×34, `oodle2` ×35, `OodleLZ_Decompress` ×12, `OodleLZ_Compress` ×5,
`Kraken` ×4, `Leviathan` ×5, `Mermaid` ×3, `Selkie` ×3, `BitKnit` ×1, `LZNA` ×1,
`OODLELZ` ×2, plus the build path `v:\devel\projects\oodle2\core\oodlelzcompressors.cpp`
and `OODLE ERROR : OodleLZ_Decompress: asked to decode Legacy compressor; not supported!`.
The codec-name table reads `LZH LZHLW LZNIB LZB16 LZBLW LZA LZNA Kraken Mermaid
BitKnit Selkie Hydra Leviathan`.

**Named API functions**, resolved by taking the string VA from `peutil.py str` and
looking up its xref in the cached map:

| VA | Name |
| --- | --- |
| `0x1479f0820` | `oo2::OodleLZ_Decompress` (whole-buffer decode) |
| `0x1479efea0` | `oo2::OodleLZ_Compress` |
| `0x1479f9710` | `oo2::newLZ_decode_chunk_phase2` |

**The dispatch chain**, all read from corpus pseudocode:

| VA | Role | Evidence |
| --- | --- | --- |
| `0x147174570` | read-path dispatch: `if (iVar5 - 0xfU < 5) FUN_147142e50(…) else FUN_147159f40(…)` | shard-001426.c:16832 |
| `0x147132390` | `nMethod` → Oodle codec id (registry lookup); every other method returns `-1` | shard-001424.c:11788 |
| `0x14716fcb0` | window + codec-descriptor setup: `uVar16 = 0x8000; if (method - 0xfU < 5) uVar16 = 0x80000;` | shard-001429.c:5500 |
| `0x147142e50` | method 15–19 decode entry (reached only from the `- 0xfU < 5` branch) | shard-001426.c:16831 |
| `0x147142cc0` | one decode step; calls `OodleLZ_Decompress` (`0x1479f0820`) or the streaming variant (`0x1479ef0e0`) | — |
| `0x147143240` | pumps a **512 KiB ring buffer** (`& 0x7ffff`, `memmove` slide on wrap) | — |

Method 8 is *not* in the `15..19` set, so it takes the `FUN_147159f40` branch — which
is the zlib path, corroborating the verified "method 8 = raw deflate".

**Where the history comes from — this is the correction that matters.** There is no
preset dictionary and no 64 KiB prefix. `FUN_14716fcb0` allocates a **512 KiB
(`0x80000`)** window for methods 15–19 (versus `0x8000` otherwise), and the decoder
runs **in place forward** inside that ring, so the history a stream can reference is
the previously decoded plaintext still sitting in the ring. Oodle's block granularity
is 256 KiB (`0x40000` = `OODLELZ_BLOCK_LEN`), and the exe carries the matching error
`dictionary backup distance must be a multiple of OODLELZ_BLOCK_LEN`.

Consequence: the earlier "offset 3,616 with only 8 bytes of output is impossible
without a dictionary" argument is **invalid** — it assumed a 64 KiB window. The
offsets are relative to a 512 KiB in-place ring, and the token grammar is Oodle's
bit-packed `newLZ`, not LZ4's nibble format.

### 4c. What is still unknown

- **Which Oodle codec is method 15.** `FUN_147132390` resolves it through data at
  `_DAT_1485ee7f0` / `_DAT_1485ee800` / `_UNK_1485ee808` (file offsets `0x85ECFF0`,
  `0x85ED000`, `0x85ED008`), which the pseudocode copies into a local struct. **Read
  measured 2026-10-02 — these are not a 16-byte key, they are u32 arrays:**

  | VA | u32 values |
  | --- | --- |
  | `0x1485ee7f0` | `17, 9, 18, 11, 15, 8, 16, 13` |
  | `0x1485ee800` | `15, 8, 16, 13` (the last four of the above) |
  | `0x1485ee808` | `16, 13` |

  They are followed by a run of NUL-terminated one-character strings (`"\0"`, `"\x01"`,
  `"\x02"`, …), which looks like a level table rather than a codec-name table.
  **15 is present in the set**, consistent with method 15 being registered here, but
  **which Oodle codec 15 names is not established** and must not be guessed. Note also
  that the pak family is 15–19 while this list stops at 18, so the set is not simply
  "the pak methods".
- **The header.** Still unexplained: `data[0:2] == 8c 06` + `data[2] == 0` in 704 of
  731 method-15 entries, `BE16(data[3:5]) == csize - 6` in 688, `BE16(data[6:8]) ==
  csize - 8` in 635, and `data[5]` is **not** constant. Because 15–19 are one family,
  the varying bytes may encode *which* Oodle codec and flags. No code was found that
  strips this prefix; look at the entry-write path around shard-001424.c:19200 and the
  entry-read at `FUN_147174570` for a `+8`/`-8` adjustment before the codec call.
- **The token grammar.** It is Oodle's, so it is not recoverable from the LZ4/deflate/
  zstd layouts that were swept (all 450 were the wrong family, which is why none
  worked).

### 4c-bis. Methodology traps found while doing this

1. **A single plaintext pair makes the oracle circular.** A decoder search that
   "reproduces the plaintext exactly" is not a valid test when the dictionary is
   filled in from that plaintext: a permissive layout *learns* the plaintext instead
   of decoding it. The tell is a match longer than the remaining output, or a
   dictionary footprint equal to the whole plaintext. Require the search to consume
   the payload exactly, cap every match length at the remaining output, and validate
   on two or more files that must share one window.
2. **A search list is a claim.** §4d originally listed LZ4/LZHAM/ZSTD/snappy/LZO/
   Brotli and concluded from the absence of those names that the codec was a custom
   fork. Oodle was never in the list, and `Oodle`/`oodle2` appear 34/35 times in the
   exe. Enumerate the *vendor* families (RAD, Epic, LZ4, zlib, Zstd, LZFSE, LZO,
   Snappy, Brotli, LZHAM, Oodle) before concluding from a negative.
3. **The corpus does resolve data addresses** — see 4e, which was also wrong.

### 4d. Ruled out

Against the ground-truth pair, decoding to the exact plaintext:

- LZ4 block, with and without a zero dictionary (4 KiB / 64 KiB), at start offsets
  0–16, both nibble orders, both offset endiannesses, minimum match 3 and 4; plus LZ4
  with a prefix window.
- raw deflate, zlib, gzip, LZMA (alone and raw), bzip2, zstd (Python 3.14
  `compression.zstd`), and zstd with a preset dictionary — at start offsets 0–12.
- raw deflate with a preset dictionary seeded from the plaintext prefix.
- Any LZ4, raw-deflate, or zlib stream at *any* offset inside the payload decoding to
  a ≥32-byte substring of the plaintext.
- A 450-layout systematic sweep (token nibble orders; literal length as
  nibble/byte/absent; offsets 2/3/4 bytes both endiannesses; match length from a
  nibble, byte or word before or after the offset; three field orders; header 6/7/8)
  requiring exact plaintext reproduction **and** full payload consumption.

All of those are now explained: they were the wrong codec family.

From the binary and from public source:

- No `LZ4`, `LZ4HC`, `LZ4F`, `LZHAM`, `ZSTD`, `snappy`, `LZO` or `Brotli` name
  strings in `NewWorld.exe`, in ASCII or UTF-16. The only `lz4` occurrence is the cvar
  name `javelin.enable-lz4-compression`, in the `javelin.gridmate.*` group (network),
  not a pak codec. The single `ZSTD` and `LZMA` occurrences are libtiff's TIFF
  compression-name table.
- The exe does carry zlib (`zlib deflate error`, `zlib inflate error`,
  `zlib not supported`, and a zlib `z_errmsg` table) — that is the method-8 path.
- Public Lumberyard `ZipFileFormat.h`: `METHOD_*` runs 0–14 and **stops at
  `METHOD_DEFLATE_AND_STREAMCIPHER_KEYTABLE = 14`. There is no 15.** `ICryPak.h`
  `ECompressionMethods = { METHOD_STORE = 0, METHOD_COMPRESS = METHOD_DEFLATE = 8,
  METHOD_COMPRESS_AND_ENCRYPT = 11 }`.
- Public Lumberyard's pak writer chooses the codec through a separate
  `CompressionCodec::Codec {ZLIB, ZSTD, LZ4}` argument while still writing method 8,
  and its LZ4 path is LZ4**F frames** — absent from our payloads.

Conclusion: method 15 is a change made in Amazon's internal Javelin fork after public
Lumberyard master froze. It is RAD Oodle (15–19 are one family), and the reader that
matters is the statically linked one named above.

### 4d-bis. A practical extraction route

Because `OodleLZ_Decompress` is **statically linked inside `NewWorld.exe`** at a known
VA, extraction does not require reimplementing Oodle. A small local harness that loads
the client's own image and calls `0x1479f0820` with the right arguments can decode a
payload. That is a bounded, self-contained route for reading and repacking content,
and it does not require distributing anything. It has not been attempted yet.

### 4e. What the corpus can and cannot search

**Corrected 2026-10-02: this section previously claimed the corpus cannot resolve
`.rdata` addresses. That was wrong.** It was concluded from a failed grep whose
pattern was bad: the corpus renders those references as `&UNK_<va>` / `_DAT_<va>`,
**without** an `0x` prefix, so searching for the bare hex VA found nothing.

Measured: `param_1[4] = (longlong)&UNK_1495318a8;` in shard-001518.c:50 is exactly
zlib's `strm->msg = "unknown compression method"`, and the corpus contains
**712,257** `&UNK_` references. Data references and jump tables (rendered as
`IMAGE_DOS_HEADER_140000000.e_magic + *(uint*)(idx*4 + TABLE_VA)`) **are** present.

So the corpus supports reference navigation. What it genuinely lacks, because it was
imported with `-noanalysis`:

- **Strings themselves.** The bytes are not typed, so you cannot grep for text. Get a
  string's VA with `peutil.py str`, then look for `&UNK_<that VA>` in the corpus.
- **Symbols.** Every function is `FUN_<va>`; the exe has no PDB.
- **Types.** Everything is `undefined8` / `longlong`.

Working filters: `- 0xfU < 5` (method 15–19 tests, 4 sites), `0x3ffff|0x40000`
(Oodle block length), and `########## 1471` for the pak module. Note that
`xrefmap.json` is a single line, so grepping it shows only the head — load it with
`json` and look the VA up, and be aware its xref values are sometimes file offsets
and sometimes VAs; resolve against the section table before trusting either.

Navigating the **analyzed** project requires Ghidra's auto-analysis, which on this
machine has **not yet completed** (2026-10-01/02, two attempts):

| Attempt | Heap | Result |
| --- | --- | --- |
| 1 | 2 GB (the default, see the `MAXMEM` bug below) | ran, still in the early analyzers after 24 min with heavy GC |
| 2 | 16 GB | vanished after ~5–9 min, no error, no `hs_err`, no event-log entry, project still at 0 MB |

Attempt 1 was diagnosed with a `jstack` thread dump: the main thread was live in
`AutoAnalysisManager.startAnalysis` → `ScalarOperandAnalyzer` →
`CodeUnitDB.getBytes`, spending its time re-reading instruction bytes while the GC
threads burned ~174 s of 1,474 s. That is the signature of an undersized heap, so
the `MAXMEM` bug below was fixed and attempt 2 given 16 GB — and attempt 2 died
instead. **The cause of attempt 2's death is not established**, and it should not
be guessed at; the 16 GB heap on a 31 GB machine that is simultaneously running a
protected game process is the leading suspect, not a proven one.

Operationally: this machine is shared with live game sessions (each of which
needs a fresh `NewWorld.exe`, and is the scarce resource — see
[wORLD-DEBUGGING.md](WORLD-DEBUGGING.md)). A multi-hour, multi-gigabyte analysis
competes directly with that. Re-run `analyze.py` when the machine is otherwise
idle, and watch the first minutes.

**A bug this uncovered in the existing tooling:** `decomp.py`, `corpus.py` and
`analyze.py` all set an environment variable named `MAXMEM`, but Ghidra 12.1.4's
`analyzeHeadless.bat` does not read it — it reads **`GHIDRA_MAXMEM`** and
**`GHIDRA_HEADLESS_MAXMEM`**, defaulting to a hard `2G`. So every run launched by
these tools silently used 2 GB. Fixed in all three (both variables are now set,
and the values are verified against the live JVM command line). The corpus itself
was unaffected in outcome: it completed all 423,579 functions under 2 GB, because
the one-function-at-a-time dump is not memory-hungry. Full analysis is.

Navigation that works today without any project, and which is the recommended
route for the codec question: `peutil.py str` for a string's VA, the cached
`xrefmap.py` map (`%LOCALAPPDATA%\Azoth\decomp\xrefmap.json`, 280,594 targets,
`lea r64,[rip+disp32]` only), and raw pointer scans in the PE. Note the limits
that matter here: the two `.rdata` RVA tables found earlier (see below) have
**zero** references in *any* form these scanners can see — no RIP-relative `lea`
in a 64 KB window around them, no u32 RVA pointer, no u64 pointer. Their
interpretation as a codec interface table is therefore **unproven**, and
[DECOMPILATION.md](DECOMPILATION.md) already warns that a table with no xrefs may
simply be decorative (the aws-sdk model table was). Do not build on it.


## 5. What this means for the plan

- **The PAK index is cheap and unblocked.** It reads central directories only;
  it does not need Oodle and it does not need the corpus.
- **Extraction of content needs an Oodle decoder.** The codec is RAD Oodle, so it
  cannot be reimplemented from the format notes. Two routes, in order of cost:
  1. **Call the client's own decoder.** `oo2::OodleLZ_Decompress` is statically linked
     at `0x1479f0820`, so a local harness can load the image and call it. Bounded,
     self-contained, nothing to distribute, not yet attempted.
  2. Name the exact codec from the registry bytes at `0x1485ee7f0` first, since the
     call needs the right codec id.
- **Repacking does not depend on Oodle.** A modified entry can be written back with
  method 8 (raw deflate) or 0, both of which the client already reads.
- Do not run the index scan while a layer-1 corpus dump is writing (disk contention);
  it is a 6-second job once the machine is free.

## Reproduce

```bash
# list every pak with its method histogram (central directories only, ~6 s)
python - <<'PY'
import zipfile, collections, glob, os
paks = sorted(glob.glob('*.pak')) + sorted(glob.glob('levels/*/*.pak'))
for p in paks:
    with zipfile.ZipFile(p) as z:
        infos = z.infolist()
    print(p, len(infos), dict(collections.Counter(i.compress_type for i in infos)), os.path.getsize(p))
PY
```

Run it with the working directory set to the install's `assets` directory.
