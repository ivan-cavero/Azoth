#!/usr/bin/env python3
r"""Corpus namer v2 — turn strings + AZ reflection + the code corpus into
candidate function names, so `decomp.py --symbol` replaces re-derivation.

The layer-1 corpus is a search index of 423,579 anonymous `FUN_<va>` functions
(DECOMP-BACKLOG 1.2). There is no PDB (1.3) and no vftable RTTI (`rtti.py`
measured the exe as `/GR-`), so names come from exactly two signals:

1. **String references.** A distinctive string's VA is referenced from corpus
   pseudocode as `&UNK_<va>` (no 0x prefix — PAK-FORMAT.md §4e). The function
   containing the reference is a naming candidate.
2. **The AZ reflection registry.** `typeindex.json` (7,052 AZ type UUIDs) and
   the in-exe property-registration blocks are the wire-key source of truth;
   type names that also appear in the RTTI TypeDescriptor pool are strong
   anchors.

This tool has three commands:

* `index` — ONE pass over the 1.1 GB of shard text, building a cached
  reference index (`%LOCALAPPDATA%\Azoth\decomp\corpus-refs.sqlite`):
  `ref(string_va) -> [function_start]`. Like `xrefmap.py`, it is built once
  and reused; delete the file to rebuild.
* `namer` — resolve seed strings to VAs with `peutil`, look them up in the
  index, and write `research/derived/namer-candidates.json` for MANUAL review.
  Candidates are never auto-inserted into `symbols.json` (repo rule: that file
  is edited by hand, one confirmed key at a time).
* `selftest` — validate the index against confirmed ground truth: the
  `publicStatusCode` string xref at `0x1483c09a0` must land inside
  `big_parser` (`0x144f40780`–`0x144f555e0`, symbols.json).

Disk only. Never touches a running process.

Usage:
    python research/tools/reversing/namer.py index
    python research/tools/reversing/namer.py namer            # default seeds
    python research/tools/reversing/namer.py namer datasheet slayer
    python research/tools/reversing/namer.py selftest
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from bisect import bisect_right
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402
import peutil  # noqa: E402

# LOCALAPPDATA is 3 levels up from Game.log (AGS/New World/Game.log).
CORPUS_DIR = (Path(default_paths()["game_log"]).parent.parent.parent
              / "Azoth" / "decomp" / "corpus" / "8654f01d324636d9")
REFS_DB = CORPUS_DIR.parent / "corpus-refs.sqlite"
OUT = Path(__file__).resolve().parents[2] / "derived" / "namer-candidates.json"

# Default seeds: DECOMP-BACKLOG §3 named loaders + movement-adjacent concepts.
DEFAULT_SEEDS = [
    "datasheet", "DataSheet", "dynamicslice", "uicanvas", "loc.xml",
    "SlayerScript", "localization", "springboard",
    "GameTransformComponent", "GameRigidBodyComponent",
    "CharacterPhysics", "CharacterController", "InputComponent",
]

HDR_RE = re.compile(r"^########## ([0-9a-f]+)-([0-9a-f]+) status=\w+ name=(\S+)", re.M)
REF_RE = re.compile(r"&UNK_([0-9a-f]+)")


def index() -> int:
    root = CORPUS_DIR
    shards = sorted((root / "shards").glob("shard-*.c"))
    if not shards:
        print(f"no corpus shards under {root}", file=sys.stderr)
        return 1
    if REFS_DB.exists():
        print(f"index already exists: {REFS_DB} (delete to rebuild)")
        return 0
    db = sqlite3.connect(REFS_DB)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("CREATE TABLE ref (va TEXT NOT NULL, fstart TEXT NOT NULL)")
    db.execute("CREATE TABLE func (fstart TEXT PRIMARY KEY, fend TEXT NOT NULL)")
    t0 = time.time()
    total_refs = 0
    batch_ref: list[tuple[str, str]] = []
    batch_fn: list[tuple[str, str]] = []

    def flush():
        nonlocal total_refs
        if batch_ref:
            db.executemany("INSERT OR IGNORE INTO ref VALUES (?,?)", batch_ref)
            total_refs += len(batch_ref)
            batch_ref.clear()
        if batch_fn:
            db.executemany("INSERT OR IGNORE INTO func VALUES (?,?)", batch_fn)
            batch_fn.clear()

    for shard in shards:
        text = shard.read_text(encoding="utf-8", errors="replace")
        # headers in document order; each ref belongs to the last header before it
        hpos = []
        hstart = []
        for m in HDR_RE.finditer(text):
            hpos.append(m.start())
            hstart.append(m.group(1))
        for m in HDR_RE.finditer(text):
            batch_fn.append((m.group(1), m.group(2)))
        for m in REF_RE.finditer(text):
            i = bisect_right(hpos, m.start()) - 1
            if i >= 0:
                batch_ref.append((m.group(1), hstart[i]))
        flush()
        print(f"  {shard.name}: cumulative refs {total_refs:,} "
              f"({time.time()-t0:.0f}s)", flush=True)
    db.commit()
    db.execute("CREATE INDEX ref_va ON ref(va)")
    db.commit()
    db.close()
    print(f"indexed {total_refs:,} refs across {len(shards)} shards in "
          f"{time.time()-t0:.0f}s -> {REFS_DB}")
    return 0


def _db() -> sqlite3.Connection:
    if not REFS_DB.exists():
        raise FileNotFoundError(
            f"no reference index at {REFS_DB}; run `namer.py index` first")
    db = sqlite3.connect(REFS_DB)
    return db


def _resolve_string(seed: str, nul_terminated: bool = True) -> list[int]:
    import peutil as _p
    pex = _p._open()
    vas = pex.find_string(seed, nul_terminated=nul_terminated)
    if not vas and nul_terminated:
        # fall back to substring matches (e.g. embedded in larger literals)
        vas = pex.find_string(seed, nul_terminated=False)
    return vas


def namer(seeds: list[str]) -> int:
    db = _db()
    if not seeds:
        seeds = DEFAULT_SEEDS
    out = []
    for seed in seeds:
        vas = _resolve_string(seed)
        if not vas:
            out.append({"seed": seed, "status": "string-not-found",
                        "candidates": []})
            continue
        cands = []
        for va in vas[:8]:
            key = f"{va:x}"
            rows = db.execute("SELECT fstart FROM ref WHERE va=?", (key,)).fetchall()
            for (fstart,) in rows[:8]:
                fend = db.execute("SELECT fend FROM func WHERE fstart=?",
                                  (fstart,)).fetchone()
                cands.append({
                    "string_va": f"0x{va:x}",
                    "function_start": f"0x{fstart}",
                    "function_end": f"0x{fend[0]}" if fend else None,
                    "proposal": re.sub(r"[^A-Za-z0-9]+", "_", seed).strip("_").lower() + "_user",
                })
        out.append({"seed": seed, "string_vas": [f"0x{v:x}" for v in vas[:8]],
                    "status": "candidates" if cands else "no-corpus-refs",
                    "candidates": cands})
    OUT.write_text(json.dumps({
        "generated_from": "corpus-refs.sqlite + peutil string resolution",
        "note": "CANDIDATES ONLY. Confirm into research/derived/symbols.json "
                "by hand, one key at a time, with a second agreeing signal.",
        "items": out,
    }, indent=1) + "\n")
    n = sum(len(i["candidates"]) for i in out)
    print(f"{n} candidates from {len(seeds)} seeds -> {OUT.name}")
    return 0


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    if not REFS_DB.exists():
        print("selftest: FAIL — no index; run `namer.py index` first")
        return 1
    db = _db()
    # ground truth 1: publicStatusCode string xref inside big_parser
    vas = _resolve_string("publicStatusCode")
    checks.append(("publicStatusCode string resolves", bool(vas)))
    ok_hit = False
    if vas:
        for va in vas:
            rows = db.execute("SELECT fstart FROM ref WHERE va=?",
                              (f"{va:x}",)).fetchall()
            for (fstart,) in rows:
                if fstart.startswith("144f4") or fstart.startswith("144f5"):
                    ok_hit = True  # inside the big_parser region
                    break
    checks.append(("publicStatusCode ref lands in big_parser region", ok_hit))
    # ground truth 2: index is populated and queryable
    n = db.execute("SELECT COUNT(*) FROM ref").fetchone()[0]
    checks.append(("index populated (>= 100k refs)", n >= 100_000))
    nf = db.execute("SELECT COUNT(*) FROM func").fetchone()[0]
    checks.append(("index has functions (>= 400k)", nf >= 400_000))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(f"{'PASS' if v else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'} ({n:,} refs, {nf:,} functions)")
    return 0 if ok else 1


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "index":
        return index()
    if cmd == "namer":
        return namer(sys.argv[2:])
    if cmd == "selftest":
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
