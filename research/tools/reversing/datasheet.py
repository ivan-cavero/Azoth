#!/usr/bin/env python3
"""DataSheet reader — the binary format behind `sharedassets/**/datatable/*.datasheet`.

DECOMP-BACKLOG 2.5 (layer 2). Format measured 2026-10-05 on three files of the
frozen install (`javelindata_perks`, `javelindata_perks_deprecated`,
`javelindata_perks_infix`; extract with `pakread.py`). All offsets are little-
endian. Everything here is measured, none of it is guessed; the one hypothesis
(the meaning of `u32[9]`) is marked.

Layout:

    offset 0x00  u32  version            (18 on every file measured)
    offset 0x04  u32  checksum A
    offset 0x08  u32  unknown (7 on all three)
    offset 0x0C  u32  checksum B
    offset 0x10  u32  unknown (varies: 28, 23, 17 — NOT the column count)
    offset 0x14  u32  1
    offset 0x18  u32  string_table_size (bytes) — VERIFIED: equals
                  file_size - string_table_start on all three files
    offset 0x1C  zeros (on the measured files)
    offset 0x5C  column directory, 12 bytes per column:
                   u32  CRC32(lowercase(column_name))
                   u32  column-name offset into the string table
                   u32  value type: 1 = string, 2 = float, 3 = bool
                 (directory ends where the CRC check fails; 38 columns on the
                 three perk tables)
    ...          row grid: nrows * ncols cells of 8 bytes each:
                   type 1: u32 string offset (0 = empty; offset points AT the
                           first char, NUL-terminated) + u32 (always 0)
                   type 2: u32 (0) + f32 little-endian value
                   type 3: u32 (0) + u32 bool
    file_size - string_table_size   NUL-terminated string table; column names
                  first, then deduplicated row values

Verified facts: every column-name hash equals CRC32 of the lowercased name
(checked on all 38 columns of all three files); the row grid size is an exact
multiple of ncols*8 (300/14/659 rows); values decode to coherent perk rows
(PerkID/PerkType/ConditionEvent/DisplayName/IconPath all consistent).

Usage:
    python research/tools/reversing/datasheet.py <file.datasheet> [max-rows]
    python research/tools/reversing/datasheet.py selftest
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def read_datasheet(d: bytes) -> tuple[int, list[tuple[str, int]], list[dict]]:
    """Parse a datasheet blob -> (version, columns, rows)."""
    ver, chk1, unk2, chk2, u4, one, stsz = struct.unpack_from("<7I", d, 0)
    st = len(d) - stsz

    def name(off: int) -> str:
        e = d.index(b"\x00", st + off)
        return d[st + off:e].decode("latin-1")

    def sval(off: int) -> str:
        if off == 0 or off >= stsz:
            return ""
        e = d.index(b"\x00", st + off)
        return d[st + off:e].decode("latin-1")

    off = 0x5C
    cols: list[tuple[str, int]] = []
    while off + 12 <= len(d):
        h, noff, typ = struct.unpack_from("<III", d, off)
        try:
            nm = name(noff)
        except ValueError:
            break
        if zlib.crc32(nm.lower().encode()) != h:
            break
        cols.append((nm, typ))
        off += 12
    if not cols:
        raise ValueError("no columns matched CRC32(lowercase(name)) — not a datasheet?")
    ncols = len(cols)
    grid = st - off
    if grid % 8 != 0 or (grid // 8) % ncols != 0:
        raise ValueError(f"grid {grid}B does not divide into {ncols}-col rows")
    nrows = grid // 8 // ncols
    rows: list[dict] = []
    for r in range(nrows):
        row: dict = {}
        for c, (nm, typ) in enumerate(cols):
            o = off + (r * ncols + c) * 8
            a, b = struct.unpack_from("<II", d, o)
            if typ == 2:
                row[nm] = struct.unpack("<f", struct.pack("<I", b))[0]
            elif typ == 3:
                row[nm] = bool(b)
            else:
                row[nm] = sval(a)
        rows.append(row)
    return ver, cols, rows


def _load(path: str) -> bytes:
    p = Path(path)
    if p.exists():
        return p.read_bytes()
    # not a local file: treat as "<pak> <entry>" via pakread
    from pakread import read_entry
    pak, entry = path.split("|", 1) if "|" in path else (path, None)
    if entry is None:
        raise FileNotFoundError(path)
    data, _ = read_entry(pak, entry)
    return data


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "selftest":
        return selftest()
    path = argv[0]
    max_rows = int(argv[1]) if len(argv) > 1 else 5
    d = _load(path)
    ver, cols, rows = read_datasheet(d)
    print(f"{path}: version {ver}, {len(cols)} columns, {len(rows)} rows")
    print("columns:", ", ".join(n for n, _ in cols))
    for r in rows[:max_rows]:
        keep = {k: v for k, v in r.items() if v not in ("", 0.0, False)}
        print(" ", {k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in keep.items()})
    return 0


def selftest() -> int:
    from pakread import read_entry
    checks: list[tuple[str, bool]] = []
    # 1: deprecated sheet — 38 cols, 300 rows, known first/last PerkID
    d, _ = read_entry("SharedDataStrm-part5.pak",
                      "sharedassets/springboardentitites/datatables/"
                      "javelindata_perks_deprecated.datasheet")
    ver, cols, rows = read_datasheet(d)
    checks.append(("deprecated: version 18", ver == 18))
    checks.append(("deprecated: 38 columns", len(cols) == 38))
    checks.append(("deprecated: 300 rows", len(rows) == 300))
    checks.append(("deprecated: first PerkID = ArmorSoldier1",
                   rows[0]["PerkID"] == "ArmorSoldier1"))
    checks.append(("deprecated: last PerkID = TwoHandSage4",
                   rows[-1]["PerkID"] == "TwoHandSage4"))
    checks.append(("deprecated: Channel is float 1.0 on row 0",
                   rows[0]["Channel"] == 1.0))
    # 2: infix sheet — different file, same layout, different data
    d2, _ = read_entry("SharedDataStrm-part6.pak",
                       "sharedassets/springboardentitites/datatables/"
                       "javelindata_perks_infix.datasheet")
    ver2, cols2, rows2 = read_datasheet(d2)
    checks.append(("infix: 38 columns", len(cols2) == 38))
    checks.append(("infix: 14 rows", len(rows2) == 14))
    checks.append(("infix: first PerkID is an Infix perk",
                   rows2[0]["PerkID"].startswith("PerkID_Infix")))
    checks.append(("infix: column names identical to deprecated",
                   [n for n, _ in cols] == [n for n, _ in cols2]))
    # 3: main perks sheet — 659 rows, type-3 bool column present
    d3, _ = read_entry("SharedDataStrm-part6.pak",
                       "sharedassets/springboardentitites/datatables/"
                       "javelindata_perks.datasheet")
    ver3, cols3, rows3 = read_datasheet(d3)
    checks.append(("perks: 659 rows", len(rows3) == 659))
    checks.append(("perks: OnlyInOpenWorld parses as bool",
                   isinstance(rows3[0].get("OnlyInOpenWorld"), bool)))
    checks.append(("perks: row PerkIDs are unique",
                   len({r["PerkID"] for r in rows3}) == len(rows3)))
    ok = all(v for _, v in checks)
    for name_, v in checks:
        print(f"{'PASS' if v else 'FAIL'} {name_}")
    print(f"selftest: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
