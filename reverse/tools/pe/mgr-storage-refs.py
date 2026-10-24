#!/usr/bin/env python3
"""Find code that writes [mgr+8] = local player entity id.

The manager is reached live through the spawn gate (FUN_146800d10) and its
`this` was 0x1d1c030ff80, vtable nw+8559dc0. The field at +8 never changes,
so we need the writer. The manager's singleton storage is referenced from
60 sites (see the earlier scan), so instead of pattern-matching every
`mov [reg+8], reg`, hook every function that references that storage and
record which one runs while the world loads. The binder is the one whose
call window overlaps the type 0x8 bundle arrival.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

# Storage of the manager singleton (TLS-backed), from the 2026-09-24 scan.
STORAGE_VA = 0x14A2FB9F0


def main() -> int:
    pe = PE(Path(default_paths()["exe"]))
    data = pe.data
    text = pe.section(".text")
    raw, rsize, va0 = text["raw"], text["rsize"], text["va"]
    hits: list[int] = []
    # rip-relative refs: the disp32 sits at some offset; test each of the
    # common instruction lengths rather than decoding properly.
    for i in range(raw, raw + rsize - 10):
        disp = struct.unpack_from("<i", data, i)[0]
        if -0x20000000 > disp > 0x20000000:
            continue
        for ilen in (6, 7, 8, 9):
            end = va0 + (i - raw) + 4
            if end + (ilen - 4) + disp == STORAGE_VA:
                hits.append(va0 + (i - raw) - (ilen - 4))
                break
    funcs = sorted(set(hits))
    print(f"{len(funcs)} refs to manager storage {STORAGE_VA:#x}")
    for f in funcs:
        print(f"  {f:#x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
