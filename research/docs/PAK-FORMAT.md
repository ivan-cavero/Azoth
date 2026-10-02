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
| `15` | **unknown** | 1,321,673 | 93.5% of everything: all `DataStrm*`, `SharedDataStrm*`, `Engine.pak`, `GameData.pak` |

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

## 4. Method 15 is a Javelin fork addition — and still unidentified

Evidence, all from `Engine.pak:config/game.xml` (method 15, 1,161 → 7,046 bytes).
The same file exists loose at `assets/Config/Game.xml`, so we have exact ground
truth: sizes and CRC-32 match, and a brute-force decode can be checked by
equality with the plaintext.

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

### 4b. The payload is an LZ-family codec with a 64 KiB prefix dictionary

After the header the payload contains **plaintext literals verbatim**. Verified
on seven entries whose first bytes are visible without decompression:

| entry | literal bytes |
| --- | --- |
| `config/game.xml` | `<ObjectS` |
| `config/cvargroups/sys_spec_full.cfg` | `; See ht` |
| `config/cvargroups/sys_spec_gsm.cfg` | `[default` |
| `config/recording.cfg` | `-- added` |
| `config/gpu/amd.txt` | `0x1002, ` |
| `config/gpu/intel.txt` | `0x8086,  ` |
| `fonts/default-ui.xml` | `<fontsha` |

The first match of `config/game.xml` is **decisive**: after the 8 literal bytes
`<ObjectS`, the encoder emits offset 3,616 (LE16) with a 5-byte match, and those
five bytes must equal `tream` to complete `<ObjectStream`. Resolving the match
against a **64 KiB prefix dictionary** puts `tream` at `D[61928..61932]` —
consistent, and the output then continues correctly to `<ObjectStream`. Offsets
of 8,293 and 27,765 appear as *first* matches on other entries, which is
impossible without a dictionary: `dictionary[65536 - offset]` is the only way
those resolve.

That is exactly the shape of `LZ4_decompress_fast_withPrefix64k` (LZ4 prefix
mode: the 64 KiB before the output pointer is addressable history). It also
explains why no other ≥4-byte literal run exists anywhere in the payload: on a
repetitive ObjectStream XML the encoder emits long matches and 1–3 byte
literals, so `P[0:8]` is the only verbatim run.

### 4c. What is still unknown

- **The exact token/length encoding.** A systematic sweep of **450 layouts** was run
  against the `config/game.xml` ground-truth pair: literal length from the token's
  high nibble (with and without 0xF extension), the low nibble, a leading byte, or
  absent; literal runs present or not; offsets of 2/3/4 bytes in both endiannesses;
  match length from either token nibble (+3 or +4, with and without extension),
  from a byte before or after the offset, or from a 16-bit word; three field
  orders; header lengths 6/7/8. Two conditions were required: reproduce the
  7,046-byte plaintext exactly, **and** consume the whole 1,161-byte payload
  (within 3 bytes). **No layout satisfies both.**
- **Where the 64 KiB dictionary comes from.** `config/game.xml` is entry #2 of
  `Engine.pak`, so only 6,258 bytes of preceding plaintext exist in that pak —
  not enough for the 27,765-byte offset seen on entry #1. A fixed preset
  dictionary (or one stored elsewhere in the pak) is the working hypothesis.

Resolving both requires reading the client's own decompressor. Guessing further
is waste; the function that maps `nMethod` to a codec is a layer-1 corpus
question, tracked as [DECOMP-PLAN.md](DECOMP-PLAN.md) work order step 3.

### 4c-bis. Methodology trap: a single plaintext pair makes the oracle circular

A decoder search that "reproduces the plaintext exactly" is **not** a valid test
when the dictionary is unknown and filled in from the plaintext as matches are
resolved. A permissive layout can then *learn* the plaintext through the
dictionary instead of decoding it, and report success. The tell is a match whose
length exceeds the remaining output, or a dictionary footprint equal to the whole
plaintext (both happened here). Require the search to also consume the payload
exactly, cap every match length at the remaining output, and validate on **two or
more files that must share one dictionary** — one file alone cannot falsify a
learning layout.

### 4d. Ruled out

Against the ground-truth pair, decoding to the exact plaintext:

- LZ4 block, with and without a zero dictionary (4 KiB / 64 KiB), at start
  offsets 0–16, both nibble orders, both offset endiannesses, minimum match 3
  and 4; plus LZ4 with a prefix window that allows offsets before the output.
- raw deflate, zlib, gzip, LZMA (alone and raw), bzip2, zstd (Python 3.14
  `compression.zstd`), and zstd with a preset dictionary — at start offsets 0–12.
- raw deflate with a preset dictionary seeded from the plaintext prefix.
- Any LZ4, raw-deflate, or zlib stream at *any* offset inside the payload
  decoding to a ≥32-byte substring of the plaintext.

From the binary and from public source:

- No `LZ4`, `LZ4HC`, `LZ4F`, `LZHAM`, `ZSTD`, `snappy`, `LZO`, or `Brotli` name
  strings in `NewWorld.exe`, in ASCII **or UTF-16**. The only `lz4` occurrence is
  the cvar name `javelin.enable-lz4-compression`, which sits in the
  `javelin.gridmate.*` group (network), not a pak codec. The single `ZSTD` and
  `LZMA` occurrences are libtiff's TIFF compression-name table next to
  `"%s compression support is not configured"` — terrain `.tif` handling.
- The exe does carry zlib (`zlib deflate error`, `zlib inflate error`,
  `zlib not supported`, and a zlib `z_errmsg` table).
- Public Lumberyard `ZipFileFormat.h`: `METHOD_*` runs 0–14 and **stops at
  `METHOD_DEFLATE_AND_STREAMCIPHER_KEYTABLE = 14`. There is no 15.**
  `ICryPak.h` `ECompressionMethods = { METHOD_STORE = 0,
  METHOD_COMPRESS = METHOD_DEFLATE = 8, METHOD_COMPRESS_AND_ENCRYPT = 11 }`.
- Public Lumberyard's pak writer (`ZipDirCacheRW.cpp`) chooses the codec through a
  separate `CompressionCodec::Codec {ZLIB, ZSTD, LZ4}` argument while still
  writing method 8, and its LZ4 path is LZ4**F frames** (`LZ4F_compressFrameBound`,
  magic `04 22 4D 18`) while the public reader's `CLZ4Decompressor` calls the
  legacy `LZ4_decompress_fast` block API. The public pair is not
  self-consistent, and our payloads carry no LZ4F magic.

Conclusion: method 15 is a change made in Amazon's internal Javelin fork after
public Lumberyard master froze. Its payload is an LZ4-family codec with a 64 KiB
prefix dictionary and a non-standard token layout. **The answer is in our exe.**

### 4e. The corpus cannot search by string — use the analyzed project instead

The layer-1 corpus was imported with `-noanalysis`, so it has no strings, no
data types, no symbols: every function is `FUN_<va>`, and references to `.rdata`
addresses do not appear at all (searching the corpus for the VA of
`zlib inflate error`, `0x14957c1f8`, returns nothing). Code-shape and numeric
searches work; string-anchored navigation does not.

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
  it does not need method 15 and it does not need the corpus.
- **Extraction of content is blocked on method 15** for `DataStrm*`,
  `SharedDataStrm*` (dynamicslices, datasheets), `Engine.pak`, and `GameData.pak`.
  The readable set today is terrain (`CoatlicueStrm`), vegetation, shader
  binaries, and every `levels/*/level.pak`.
- **Repacking does not depend on method 15.** A modified entry can be written
  back with method 8 (raw deflate) or 0, both of which the client already reads.
  Only *reading* the existing compressed entries needs the codec.
- Do not run the index scan while the layer-1 dump is writing (disk contention);
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
