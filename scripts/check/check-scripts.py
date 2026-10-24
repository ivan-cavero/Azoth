#!/usr/bin/env python3
"""Fail if scripts/catalog.json drifts from files on disk."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
SKIP_NAMES = {"_reorg_layout.py", "_fix_roots.py", "rust_openssl_env.py"}


def main() -> int:
    catalog = json.loads((SCRIPTS / "catalog.json").read_text(encoding="utf-8"))
    listed = {meta["path"].replace("\\", "/") for meta in catalog["scripts"].values()}
    on_disk = {
        p.relative_to(SCRIPTS).as_posix()
        for p in SCRIPTS.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".ps1"}
        and p.name not in SKIP_NAMES
        and p.parent != SCRIPTS
    }
    missing = sorted(listed - on_disk)
    extra = sorted(on_disk - listed)
    if missing or extra:
        if missing:
            print("check-scripts: catalog entries missing on disk:")
            for item in missing:
                print(f"  {item}")
        if extra:
            print("check-scripts: on-disk scripts not in catalog:")
            for item in extra:
                print(f"  {item}")
        return 1
    print(f"check-scripts: ok ({len(listed)} scripts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
