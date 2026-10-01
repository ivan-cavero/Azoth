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

**Prefix.** Every method-15 payload starts with a 7-byte-looking header whose
shape repeats across unrelated files:

| file | header | byte3 | byte4 | byte5 | byte6 | byte7 |
| --- | --- | --- | --- | --- | --- | --- |
| `config/game.xml` | `8c 06 00 04 83 88 04 81` | `04` | `83` | `88` | `04` | `81` |
| `fonts/default-ui.xml` | `8c 06 00 00 bd 88 00 bb` | `00` | `bd` | `88` | `00` | `bb` |
| `config/gpu/intel.txt` | `8c 06 00 02 7a 88 02 78` | `02` | `7a` | `88` | `02` | `78` |
| `engineassets/materials/test/sky.mtl` | `8c 06 00 01 0b 88 01 09` | `01` | `0b` | `88` | `01` | `09` |

Bytes 0, 1 (`8c 06`) and 5 (`88`) are fixed; byte 6 repeats byte 3; byte 7 is
byte 4 minus 2. That is structure, not compressed data, so a header exists — but
its length is not yet pinned, and it is not in the public Lumberyard source.

**Payload.** For `config/game.xml` the first 8 output bytes `<ObjectS` appear
verbatim at `C[8:16]`, and a byte `0x81` at `C[7]` is exactly an LZ4 token with
literal length 8. That looked like LZ4 with a 7-byte prefix — until the rest:
the payload contains **no other literal run of 4 bytes or more** (checked by
4-gram indexing of the plaintext against the whole 1,161-byte payload), and the
first match would need an offset of 3,616 with only 8 bytes of output. Both are
impossible for plain LZ4.

**Ruled out** (each tried against ground truth, decoding to the exact plaintext):

- LZ4 block, with and without a zero dictionary (4 KiB / 64 KiB), at start
  offsets 0–16, both nibble orders, both offset endiannesses, minimum match 3
  and 4.
- raw deflate, zlib, gzip, LZMA (alone and raw), bzip2, zstd (Python 3.14
  `compression.zstd`), and zstd with a preset dictionary — at start offsets 0–12.
- raw deflate with a preset dictionary seeded from the plaintext prefix.
- Any LZ4, raw-deflate, or zlib stream at *any* offset inside the payload
  decoding to a ≥32-byte substring of the plaintext.

**Ruled out from the binary and from public source:**

- No `LZ4`, `LZ4HC`, `LZHAM`, `ZSTD`, `LZO`, or `Brotli` name strings in
  `NewWorld.exe`. The exe does carry zlib (`zlib deflate error`,
  `zlib inflate error`, `zlib not supported`, and a zlib `z_errmsg` table).
- Public Lumberyard `ICryPak.h`: `ECompressionMethods = { METHOD_STORE = 0,
  METHOD_COMPRESS = METHOD_DEFLATE = 8, METHOD_COMPRESS_AND_ENCRYPT = 11 }`.
- Public Lumberyard `ZipFileFormat.h`: `METHOD_*` runs 0–14 and **stops at
  `METHOD_DEFLATE_AND_STREAMCIPHER_KEYTABLE = 14`. There is no 15.**
- Public Lumberyard's pak writer (`ZipDirCacheRW.cpp`) chooses the codec through a
  separate `CompressionCodec::Codec {ZLIB, ZSTD, LZ4}` argument while still
  writing method 8, and its LZ4 path is LZ4**F frames** (`LZ4F_compressFrameBound`,
  magic `04 22 4D 18`) — that magic is absent from our payloads. The public
  reader's `CLZ4Decompressor` uses the legacy `LZ4_decompress_fast` block API
  instead, so the public pair is not self-consistent either.

Conclusion: method 15 is a change made in Amazon's internal Javelin fork after
public Lumberyard master froze. Guessing further is waste; **the answer is in our
exe**, in the function that turns `nMethod` into a decompressor. That is a layer-1
corpus question and is tracked in [DECOMP-PLAN.md](DECOMP-PLAN.md) work order
step 3.

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
