#!/usr/bin/env python3
"""PAK index for the New World install — layer 2 of the decompilation plan.

Reads every `assets/*.pak` and `assets/levels/*/level.pak` **central directory
only** (no payload bytes), writes a sqlite index under
`.azoth/cache/pak-index/pakindex.db` and a small tracked summary at
`research/derived/pak-summary.json`.

Measured baseline (2026-10-01, PAK-FORMAT.md): 123 paks, 1,413,205 entries in
6.1 s of central-directory reads; methods 0 / 8 / 15 only. The selftest checks
exactly that baseline, so a rebuild that disagrees is loud.

Disk only. Never touches a running process.

Usage:
    python az.py re pak-index build      # index + summary
    python az.py re pak-index stats      # summary of the db
    python az.py re pak-index find slab  # entries by substring
    python az.py re pak-index selftest
"""

from __future__ import annotations

import collections
import json
import sqlite3
import struct
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402

BASELINE = {
    "entries": 1413205,
    "methods": {0: 90949, 8: 583, 15: 1321673},
    "paks": 123,
    "empty_paks": 2,  # SharedDataStrm-part12/13: a bare 22-byte EOCD, no entries
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS entry (
    path   TEXT NOT NULL,
    pak    TEXT NOT NULL,
    ext    TEXT NOT NULL,
    csize  INTEGER NOT NULL,
    usize  INTEGER NOT NULL,
    crc    INTEGER NOT NULL,
    method INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS entry_path ON entry(path);
CREATE INDEX IF NOT EXISTS entry_pak  ON entry(pak);
"""


def _db_path() -> Path:
    d = default_paths()["state"] / "cache" / "pak-index"
    d.mkdir(parents=True, exist_ok=True)
    return d / "pakindex.db"


def list_paks(assets: Path) -> list[Path]:
    paks = sorted(assets.glob("*.pak")) + sorted(assets.glob("levels/*/*.pak"))
    return paks


def build() -> int:
    assets = default_paths()["install"] / "assets"
    paks = list_paks(assets)
    if not paks:
        print(f"no paks found under {assets}", file=sys.stderr)
        return 1
    db = _db_path()
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    per_method: dict[int, int] = collections.Counter()
    per_pak: dict[str, int] = {}
    per_ext: dict[str, int] = collections.Counter()
    t0 = time.time()
    for pak in paks:
        rel = str(pak.relative_to(assets)).replace("\\", "/")
        rows = []
        with zipfile.ZipFile(pak) as z:
            infos = z.infolist()
            for info in infos:
                ext = Path(info.filename).suffix.lstrip(".").lower() or "(none)"
                rows.append(
                    (info.filename, rel, ext, info.compress_size,
                     info.file_size, info.CRC, info.compress_type)
                )
                per_method[info.compress_type] += 1
                per_ext[ext] += 1
        per_pak[rel] = len(rows)
        con.executemany("INSERT INTO entry VALUES (?,?,?,?,?,?,?)", rows)
        print(f"  {rel}: {len(rows)} entries")
    con.commit()
    con.close()
    elapsed = time.time() - t0
    total = sum(per_pak.values())
    summary = {
        "generated": time.strftime("%Y-%m-%d"),
        "exe_sha256_prefix": "8654f01d324636d9",
        "paks": len(paks),
        "entries": total,
        "methods": {str(k): v for k, v in sorted(per_method.items())},
        "extensions_top20": dict(per_ext.most_common(20)),
        "entries_per_pak": per_pak,
        "build_seconds": round(elapsed, 1),
        "note": "Central directories only. Full index at "
                ".azoth/cache/pak-index/pakindex.db (gitignored).",
    }
    out = default_paths()["research"] / "derived" / "pak-summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"indexed {total:,} entries across {len(paks)} paks in {elapsed:.1f}s")
    print(f"summary -> {out}")
    return 0


def _load(con: sqlite3.Connection):
    con.row_factory = sqlite3.Row


def stats() -> int:
    con = sqlite3.connect(_db_path())
    _load(con)
    total = con.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    methods = con.execute(
        "SELECT method, COUNT(*) c FROM entry GROUP BY method ORDER BY method"
    ).fetchall()
    print(f"{total:,} entries")
    for r in methods:
        print(f"  method {r['method']}: {r['c']:,}")
    return 0


def find(needle: str, limit: int = 40) -> int:
    con = sqlite3.connect(_db_path())
    _load(con)
    rows = con.execute(
        "SELECT path, pak, method, csize, usize, crc FROM entry "
        "WHERE path LIKE ? LIMIT ?", (f"%{needle}%", limit),
    ).fetchall()
    for r in rows:
        print(f"{r['pak']}::{r['path']} method={r['method']} "
              f"{r['csize']}->{r['usize']} crc={r['crc']:08x}")
    print(f"{len(rows)} shown (limit {limit})")
    return 0


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    if not _db_path().exists():
        print("selftest: FAIL — no index; run `pakindex.py build` first")
        return 1
    con = sqlite3.connect(_db_path())
    _load(con)
    total = con.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    npak = con.execute("SELECT COUNT(DISTINCT pak) FROM entry").fetchone()[0]
    methods = dict(
        con.execute("SELECT method, COUNT(*) FROM entry GROUP BY method").fetchall()
    )
    checks.append(("total entries match baseline", total == BASELINE["entries"]))
    checks.append(("pak count matches baseline (total minus empty paks)",
                   npak == BASELINE["paks"] - BASELINE["empty_paks"]))
    checks.append(("method histogram matches baseline",
                   methods == BASELINE["methods"]))
    row = con.execute(
        "SELECT path, pak, usize, crc, method FROM entry WHERE method=8 LIMIT 1"
    ).fetchone()
    checks.append(("method-8 entries present", row is not None))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(f"{'PASS' if v else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'} "
          f"({total:,} entries, {npak} paks, methods {methods})")
    return 0 if ok else 1


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "build":
        return build()
    if cmd == "stats":
        return stats()
    if cmd == "find":
        return find(sys.argv[2] if len(sys.argv) > 2 else "")
    if cmd == "selftest":
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
