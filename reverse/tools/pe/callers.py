"""Find E8 call xrefs to a target VA (single pass over .text)."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    target = int(sys.argv[1], 16)
    text = pe.section(".text")
    data = pe.data
    hits = []
    for off in range(text["raw"], text["raw"] + text["rsize"] - 5):
        if data[off] == 0xE8:
            rel = struct.unpack_from("<i", data, off + 1)[0]
            va = text["va"] + (off - text["raw"])
            if va + 5 + rel == target:
                hits.append(va)
    print(len(hits), "callers:", [hex(h) for h in hits])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
