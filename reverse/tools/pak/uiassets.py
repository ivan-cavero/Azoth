#!/usr/bin/env python3
"""Classify the LyShine UI assets in the existing PAK index into one inventory.

WHY THIS EXISTS
===============
The LyShine UI pipeline (`odd/tasks/lyshine-ui.md`, task T2) needs an organized
inventory of what UI exists before a reader, a preview renderer or a writer can
touch it. The bytes are already described by the PAK index
(`.azoth/cache/pak-index/pakindex.db`, built by `pak-index`): one row per PAK
entry with its path, sizes and compression method. So the inventory is a pure
classification over that index -- no PAK is opened and no payload is ever
decompressed, which keeps it reproducible on any machine that has the index.

SCOPE
=====
UI lives under `lyshineui/` inside `DataStrm*.pak`. This tool calls a path a UI
asset when it is:

  * under `lyshineui/` -- counted by extension (`canvas` / `luac` / `dds` /
    `other`); or
  * a `*.loc.xml` localization file -- the display strings the UI shows
    (`loc`). Those live under `localization/`, outside `lyshineui/`.

Every other path is not a UI asset and is not counted.

WHAT IT WRITES
==============
`research/derived/ui-assets.json`: per-kind count, total compressed and
uncompressed size, method histogram, a small representative sample and the
classification rules. The evidence word is `measured`: every number comes from
the index, which was itself read from the install's central directories.

Usage:
    python ef.py re uiassets build [--out FILE]
    python ef.py re uiassets selftest
"""

from __future__ import annotations

import collections
import json
import sqlite3
import sys
import time
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402

UI_ROOT = "lyshineui/"
LOC_SUFFIX = ".loc.xml"
KINDS = ("canvas", "luac", "dds", "loc", "other")
SAMPLE_LIMIT = 5

# Measured 2026-11-01 on client 1.460.6033.6024067: under `lyshineui/` there are
# exactly 164 canvases, 1,100 compiled Lua scripts, 54,334 sprites and 56,016
# entries in total (the rest are fonts, sprites, slices and video). The selftest
# pins them so an index that drifts is loud instead of silently wrong.
EXPECTED = {
    "canvas": 164,
    "luac": 1100,
    "dds": 54334,
    "lyshineui": 56016,
}

RULES = {
    "canvas": "path under lyshineui/ with extension .dynamicuicanvas",
    "luac": "path under lyshineui/ with extension .luac",
    "dds": "path under lyshineui/ with extension .dds",
    "loc": "path ending in .loc.xml (localization text; outside lyshineui/)",
    "other": "any other path under lyshineui/ (font, sprite, slice, video, ...)",
    "excluded": "every path outside lyshineui/ that is not a .loc.xml",
}


def _db_path() -> Path:
    return default_paths()["state"] / "cache" / "pak-index" / "pakindex.db"


def classify(path: str) -> str | None:
    """Return the kind of a PAK entry path, or None when it is not a UI asset."""
    p = path.replace("\\", "/").lower()
    if p.endswith(LOC_SUFFIX):
        return "loc"
    if not p.startswith(UI_ROOT):
        return None
    ext = PurePosixPath(p).suffix.lstrip(".").lower()
    if ext == "dynamicuicanvas":
        return "canvas"
    if ext == "luac":
        return "luac"
    if ext == "dds":
        return "dds"
    return "other"


def scan(db_path: Path) -> dict[str, dict]:
    """Classify every UI asset row in the index. Reads the DB only, never a PAK.

    Returns `kind -> {count, csize, usize, methods, sample}` in a deterministic
    path order so the derived JSON is stable across runs.
    """
    buckets: dict[str, dict] = {
        kind: {"count": 0, "csize": 0, "usize": 0,
               "methods": collections.Counter(), "sample": []}
        for kind in KINDS
    }
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT path, csize, usize, method FROM entry "
            "WHERE path LIKE ? OR path LIKE ? ORDER BY path",
            (f"{UI_ROOT}%", f"%{LOC_SUFFIX}"),
        )
        for path, csize, usize, method in rows:
            kind = classify(path)
            if kind is None:
                continue  # e.g. a lyshineui-like path that is not under UI_ROOT
            bucket = buckets[kind]
            bucket["count"] += 1
            bucket["csize"] += csize
            bucket["usize"] += usize
            bucket["methods"][method] += 1
            if len(bucket["sample"]) < SAMPLE_LIMIT:
                bucket["sample"].append(
                    {"path": path, "csize": csize, "usize": usize, "method": method}
                )
    finally:
        con.close()
    return buckets


def _classifiable(entries: dict[str, dict]) -> int:
    """Entries this inventory covers (lyshineui/ plus localization loc.xml)."""
    return sum(entries[kind]["count"] for kind in ("canvas", "luac", "dds", "other"))


def build_document(db_path: Path) -> dict:
    """The full derived inventory as JSON-safe data."""
    buckets = scan(db_path)
    kinds = {
        kind: {
            "count": b["count"],
            "csize": b["csize"],
            "usize": b["usize"],
            "methods": {str(m): c for m, c in sorted(b["methods"].items())},
            "sample": b["sample"],
        }
        for kind, b in buckets.items()
    }
    lyshineui = _classifiable(buckets)
    return {
        "generated": time.strftime("%Y-%m-%d"),
        "evidence": "measured",
        "source": "state/cache/pak-index/pakindex.db",
        "scope": "lyshineui/ inside DataStrm*.pak, plus *.loc.xml localization",
        "rules": RULES,
        "kinds": kinds,
        "totals": {
            "lyshineui": lyshineui,
            "classified": lyshineui + buckets["loc"]["count"],
            "csize": sum(b["csize"] for b in buckets.values()),
            "usize": sum(b["usize"] for b in buckets.values()),
        },
    }


def cmd_build(out: str | None) -> int:
    db = _db_path()
    if not db.exists():
        print(f"index not found: {db}", file=sys.stderr)
        print("run `python ef.py re pak-index build` first", file=sys.stderr)
        return 1
    document = build_document(db)
    target = Path(out) if out else default_paths()["research"] / "derived" / "ui-assets.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    kinds = document["kinds"]
    print(f"{document['totals']['lyshineui']:,} lyshineui entries "
          f"(canvas {kinds['canvas']['count']:,}, luac {kinds['luac']['count']:,}, "
          f"dds {kinds['dds']['count']:,}, other {kinds['other']['count']:,}) "
          f"+ {kinds['loc']['count']:,} loc")
    print(f"wrote {target}")
    return 0


def selftest(db_path: Path | None = None) -> int:
    db = db_path or _db_path()
    if not db.exists():
        print(f"selftest: SKIP - no index at {db}")
        return 0
    kinds = scan(db)
    got = {
        "canvas": kinds["canvas"]["count"],
        "luac": kinds["luac"]["count"],
        "dds": kinds["dds"]["count"],
        "lyshineui": _classifiable(kinds),
    }
    checks = [
        (f"lyshineui/ has exactly {EXPECTED['canvas']} canvases (got {got['canvas']})",
         got["canvas"] == EXPECTED["canvas"]),
        (f"lyshineui/ has exactly {EXPECTED['luac']} luac scripts (got {got['luac']})",
         got["luac"] == EXPECTED["luac"]),
        (f"lyshineui/ has exactly {EXPECTED['dds']} dds sprites (got {got['dds']})",
         got["dds"] == EXPECTED["dds"]),
        (f"lyshineui/ has exactly {EXPECTED['lyshineui']} entries in total "
         f"(got {got['lyshineui']})",
         got["lyshineui"] == EXPECTED["lyshineui"]),
    ]
    ok = all(value for _, value in checks)
    for name, value in checks:
        print(f"{'PASS' if value else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "build":
        out = argv[argv.index("--out") + 1] if "--out" in argv else None
        return cmd_build(out)
    if cmd == "selftest":
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
