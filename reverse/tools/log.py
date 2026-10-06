#!/usr/bin/env python3
"""Ingest an existing Game.log. Live watch lives in tools/capture."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402


def capture_script() -> Path:
    return default_paths()["research"] / "tools" / "capture" / "nw_capture.py"


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse Game.log from disk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest", help="parse an existing Game.log")
    i.add_argument("--log")
    i.add_argument("--session")
    w = sub.add_parser("hint-watch", help="how to watch the live log")
    args = ap.parse_args()
    p = default_paths()
    cap = capture_script()
    if args.cmd == "hint-watch":
        print("Live Game.log is paired with NIC capture (pktmon).")
        print("  research\\tools\\capture\\Start-NwCapture.bat")
        print(
            "Log only, no NIC: python tools/capture/nw_capture.py watch --session <dir>"
        )
        return 0
    log = Path(args.log) if args.log else p["game_log"]
    session = args.session or str(p["research"] / "sessions" / "log_ingest")
    cmd = [
        sys.executable,
        "-u",
        str(cap),
        "ingest",
        "--repo",
        str(p["research"]),
        "--log",
        str(log),
        "--session",
        session,
    ]
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
