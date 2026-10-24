#!/usr/bin/env python3
"""Fail if tracked files contain machine-specific user home paths."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Windows users\, Unix /home/, and explicit C:\Users\
PATTERNS = [
    re.compile(r"(?i)C:\\Users\\[^\\/\s\"']+"),
    re.compile(r"(?i)/Users/[A-Za-z0-9_.-]+/"),
    re.compile(r"(?i)/home/[A-Za-z0-9_.-]+/"),
]

ALLOW_SUFFIXES = {".md"}  # docs may mention example paths once; still scan lightly


def tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / p for p in out.decode().split("\0") if p]


def skipped(rel: str) -> bool:
    """Archives, journals, and derived dumps may quote historical paths."""
    return (
        rel.startswith("docs/archive/")
        or rel.startswith("docs/journal/")
        or rel.startswith("docs/sessions/")
        or rel.startswith("research/derived/")
        or rel.endswith("check-paths.py")
        or rel.endswith("doctor.py")
    )


def main() -> int:
    bad: list[str] = []
    for path in tracked_files():
        if not path.is_file():
            continue
        if path.suffix in {".png", ".jpg", ".dll", ".bin", ".exe", ".wasm"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if skipped(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in PATTERNS:
            if pat.search(text):
                bad.append(f"{rel}: matches {pat.pattern}")
                break
    if bad:
        print("check-paths: machine-specific paths in tracked files:")
        for line in bad:
            print(f"  {line}")
        return 1
    print("check-paths: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
