#!/usr/bin/env python3
"""List every site in NewWorld.exe that references a target VA.

WHY THIS EXISTS
===============
`python ef.py re xref xrefs --needle <hex>` (pe/xrefmap.py) builds a map keyed
on `lea r64,[rip+disp]` targets that look like strings, and `pe/ripxref.py`
only prints raw offsets inside a VA window. Neither answers "who references
this vtable slot or this request-bus name": a vtable entry is an absolute
64-bit pointer stored in `.rdata`, and a bus name is loaded with a RIP-relative
displacement in `.text`. That gap is what blocks locating the UI controller for
`PaperdollComponentServerFacet_ServerEquipItem` (0xf37).

This tool answers both directions for one or more target VAs:

* DATA - every 8-byte little-endian occurrence of the VA in `.rdata`/`.data`
         (vtable entries, pointer tables);
* CODE - every `disp32` field at file offset `p` in `.text` whose RIP-relative
         target is the VA, i.e. `read_u32(p) == (VA - (va(p) + 4)) & 0xffffffff`
         (the displacement is the last four bytes of the instruction, so the
         instruction ends at `p + 4`). Each hit is reported with a best-effort
         containing-instruction VA and the 16 bytes around it.

Every hit is labelled `data` or `code`; both kinds are reported because a
target is often referenced both ways (a vtable slot holds the code pointer and
code loads the string). A coincidental `disp32` that lands on the target while
scanning the whole `.text` range is possible; the printed bytes are there to
tell the two apart.

Dependency-free: reuses the repository PE reader (`corpus/catalog.py`), reads
disk only, never opens the game process.

Usage:
  python reverse/tools/pe/xref-data.py 0x148554a08
  python reverse/tools/pe/xref-data.py --exe <path> 0x148554a08 0x14841b508 0x14853b838
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from catalog import PE  # noqa: E402

DEFAULT_DATA_SECTIONS = (".rdata", ".data")


class Hit(NamedTuple):
    """One reference site.

    kind    - "data" (absolute pointer) or "code" (RIP-relative displacement)
    section - PE section the site lives in
    va      - site VA (the pointer entry, or the displacement field)
    insn_va - best-effort containing-instruction VA for code hits, else None
    """

    kind: str
    section: str
    va: int
    insn_va: int | None


def _insn_start(data: bytes, disp_off: int) -> int | None:
    """Best-effort file offset of the instruction owning the disp32 at disp_off.

    A RIP-relative `REX (8D|8B) modrm disp32` instruction ends right after the
    displacement, so its start sits exactly three bytes before the field. Other
    RIP-relative forms exist; this returns None rather than guess wrong.
    """
    if disp_off >= 3:
        rex, op, modrm = data[disp_off - 3], data[disp_off - 2], data[disp_off - 1]
        if 0x40 <= rex <= 0x4F and op in (0x8D, 0x8B) and (modrm & 0xC7) == 0x05:
            return disp_off - 3
    return None


def scan_data_refs(
    pe: PE, targets: list[int], sections: tuple[str, ...] = DEFAULT_DATA_SECTIONS
) -> dict[int, list[Hit]]:
    """Absolute 64-bit pointer occurrences of each target in data sections."""
    found: dict[int, list[Hit]] = {t: [] for t in targets}
    for name in sections:
        try:
            sec = pe.section(name)
        except KeyError:
            continue
        start, end = sec["raw"], sec["raw"] + sec["rsize"]
        for target in targets:
            needle = struct.pack("<Q", target)
            offset = start
            while True:
                offset = pe.data.find(needle, offset, end)
                if offset < 0:
                    break
                found[target].append(Hit("data", name, pe.foff_to_va(offset), None))
                offset += 1
    return found


def scan_code_refs(pe: PE, targets: list[int]) -> dict[int, list[Hit]]:
    """RIP-relative references to each target across the whole `.text` section."""
    text = pe.section(".text")
    raw, rsize, text_va = text["raw"], text["rsize"], text["va"]
    data = pe.data
    wanted = set(targets)
    found: dict[int, list[Hit]] = {t: [] for t in targets}
    unpack_from = struct.unpack_from
    for offset in range(raw, raw + rsize - 3):
        disp = unpack_from("<i", data, offset)[0]
        end_va = text_va + (offset - raw) + 4
        target = end_va + disp
        if target in wanted:
            insn_off = _insn_start(data, offset)
            found[target].append(
                Hit(
                    "code",
                    ".text",
                    end_va - 4,
                    text_va + (insn_off - raw) if insn_off is not None else None,
                )
            )
    return found


def scan_many(
    pe: PE, targets: list[int], sections: tuple[str, ...] = DEFAULT_DATA_SECTIONS
) -> dict[int, list[Hit]]:
    """Every reference to each target, ordered by site VA."""
    found = scan_data_refs(pe, targets, sections)
    code = scan_code_refs(pe, targets)
    for target in targets:
        found[target].extend(code[target])
        found[target].sort(key=lambda h: (h.va, h.kind))
    return found


def scan(pe: PE, target: int, sections: tuple[str, ...] = DEFAULT_DATA_SECTIONS) -> list[Hit]:
    """Every reference to one target, ordered by site VA."""
    return scan_many(pe, [target], sections)[target]


def _hex_window(data: bytes, foff: int, n: int = 16) -> str:
    """`n` bytes of context around a file offset, as spaced hex."""
    start = max(0, foff - n // 2)
    return " ".join(f"{b:02x}" for b in data[start : start + n])


def render(pe: PE, targets: list[int], found: dict[int, list[Hit]]) -> None:
    for target in targets:
        hits = found[target]
        data_hits = sum(1 for h in hits if h.kind == "data")
        code_hits = len(hits) - data_hits
        print(f"target {hex(target)}: {len(hits)} reference(s) ({data_hits} data, {code_hits} code)")
        for hit in hits:
            foff = pe.va_to_foff(hit.va)
            window = _hex_window(pe.data, foff) if foff is not None else ""
            insn = f" insn={hex(hit.insn_va)}" if hit.insn_va is not None else ""
            print(f"  [{hit.kind}] {hit.section} @{hex(hit.va)}{insn}  {window}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="+", help="target VA(s), hex")
    ap.add_argument("--exe", help="PE to scan (default: the pinned client build)")
    ap.add_argument(
        "--sections",
        default=",".join(DEFAULT_DATA_SECTIONS),
        help="data sections scanned for absolute pointers (default: .rdata,.data)",
    )
    args = ap.parse_args()

    targets = [int(t, 16) for t in args.targets]
    sections = tuple(s for s in args.sections.split(",") if s)
    exe = Path(args.exe) if args.exe else default_paths()["exe"]
    pe = PE(exe)
    print(f"exe: {exe}")
    render(pe, targets, scan_many(pe, targets, sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
