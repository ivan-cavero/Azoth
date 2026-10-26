"""Find every `lea reg,[rip+disp32]` in .text that resolves to one of the given VAs.

WHY THIS EXISTS
===============
Several questions in this project are "which code uses this string / this descriptor", and the
existing tools do not answer it reliably:

* `reverse/tools/xrefmap.py` only covers a cached target set;
* a naive whole-`.text` linear `md.disasm` sweep - which I tried first - **desynchronises** on
  data and padding. Measured 2026-10-13: that sweep reported **0** references to the
  `ALCReplicatedState` name at `0x1480fed90`, while the function that creates the object
  (`FUN_142a3b050`) plainly contains `142a3b117 lea rdx,[rip+0x56c3c72]` -> `0x1480fed90`.
  One desynchronised byte silently swallows every later reference, and the result looks like a
  confident negative.

This tool cannot desync: it matches the *instruction pattern* (`RIP`-relative LEA, encodings
`48 8D` and `4C 8D` with modrm.rm = 101), decodes exactly that instruction, and returns only the
ones whose target is in the requested set. Every hit is a decoded instruction whose displacement
was computed, not a byte coincidence.

Usage:
    python reverse/tools/find-rip-lea.py 0x1480fed90 0x1480ffa68
    python reverse/tools/find-rip-lea.py --string ALCReplicatedState
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from catalog import PE  # noqa: E402

# modrm mod=00, rm=101 -> RIP-relative displacement follows
RIP_MODRM = (0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D)


def scan(pe: PE, targets: set[int]) -> dict[int, list[int]]:
    import capstone

    text = pe.section(".text")
    raw, rsize, tva = text["raw"], text["rsize"], text["va"]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    data = pe.data
    out: dict[int, list[int]] = {t: [] for t in targets}
    for off in range(raw, raw + rsize - 7):
        b0, b1 = data[off], data[off + 1]
        if b0 not in (0x48, 0x4C) or b1 != 0x8D:
            continue
        modrm = data[off + 2]
        if modrm & 0xC7 != 0x05:  # mod=00, rm=101
            continue
        disp = struct.unpack_from("<i", data, off + 3)[0]
        va = tva + (off - raw)
        target = va + 7 + disp
        if target in targets:
            out[target].append(va)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", help="hex VAs")
    ap.add_argument("--string", action="append", default=[],
                    help="resolve this exact NUL-terminated string to its VA first")
    ap.add_argument("--exe")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else default_paths()["exe"]
    pe = PE(exe)

    wanted: dict[int, str] = {}
    for t in args.targets:
        wanted[int(t, 16)] = ""
    for s in args.string:
        fo = pe.data.find(s.encode() + b"\0")
        if fo < 0:
            print(f"string not found: {s!r}")
            return 1
        va = pe.foff_to_va(fo)
        if va is None:
            print(f"string {s!r} at an unmapped offset")
            return 1
        wanted[va] = s

    hits = scan(pe, set(wanted))
    for va, label in sorted(wanted.items()):
        print(f"\n{hex(va)}  {label}: {len(hits[va])} RIP-relative reference(s)")
        for ref in hits[va][:40]:
            print(f"    {hex(ref)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
