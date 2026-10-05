Vendored third-party decoder: ooz (Kraken / Mermaid / Selkie / Leviathan / LZNA / BitKnit)

Source: https://github.com/powzix/ooz
Commit: 1d1051adab00420707bc0b59f9002cac932d7985 (2026-09-13)
License: zlib (see ooz upstream repository)

Files vendored unmodified:
- kraken.cpp   — the Kraken-family decoder (only file compiled by pakread.py)
- kraken.h

Added by Azoth (not upstream):
- ooz_shim.cpp — a tiny ctypes shim that allocates dst_len + 64 bytes because
  ooz's decompressor may write up to SAFE_SPACE (64) bytes past the end of the
  destination buffer (documented warning above Kraken_Decompress). The wrapper
  wheel `kraken-decompressor` allocates exactly dst_len, which is why it heap
- corrupts (0xc0000374) on some New World payloads (first reproduction:
  SharedDataStrm-part6.pak::javelindata_perks.datasheet, 2026-10-05).

This is public open-source code, not decompiled game code.
