#!/usr/bin/env python3
"""Dump the Javelin GridMate type-id table from the private NewWorld binary.

The captured replay is build 1.365; the client we run is 1.400. GridMate
assigns sequential type ids, so any insertion/removal between builds shifts
every id after it. If the replay carries 1.365 ids and the client 1.400
dispatches by id, the client acks the datagrams (transport is fine) and
then silently drops messages it cannot map — exactly the observed symptom.

The table lives at 0x14860afd8 in .rdata on this build. We print the raw
u32 run so ids can be matched against the ids the replay uses, and look for
the reflection-registry name block near it.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from catalog import PE  # noqa: E402

TABLE_VA = 0x14860AFD8
COUNT = 96


def main() -> int:
    paths = default_paths()
    pe = PE(Path(paths["exe"]))
    data = pe.data
    off = pe.va_to_foff(TABLE_VA)
    print(f"table VA {TABLE_VA:#x} -> file {off:#x}")
    vals = struct.unpack_from(f"<{COUNT}I", data, off)
    for row in range(0, COUNT, 8):
        chunk = vals[row : row + 8]
        cells = " ".join(f"{v:08x}" for v in chunk)
        print(f"  {TABLE_VA + row * 4:#x}: {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
