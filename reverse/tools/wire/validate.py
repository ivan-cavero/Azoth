#!/usr/bin/env python3
"""Compile-check scripts and verify the local install. Does not launch the game."""

from __future__ import annotations

import compileall
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402


def main() -> int:
    p = default_paths()
    repo = p["repo"]
    errors: list[str] = []
    ok: list[str] = []

    re_dir = repo / "reverse" / "tools"
    cap_dir = p["research"] / "tools" / "capture"
    if not compileall.compile_dir(str(re_dir), quiet=1, maxlevels=0):
        errors.append("compile reverse/tools")
    else:
        ok.append("compile reverse/tools")
    if not compileall.compile_file(str(cap_dir / "nw_capture.py"), quiet=1):
        errors.append("compile research/tools/capture/nw_capture.py")
    else:
        ok.append("compile research/tools/capture/nw_capture.py")

    if p["exe"].is_file():
        ok.append(f"exe {p['exe'].stat().st_size} bytes")
    else:
        errors.append(f"missing exe {p['exe']}")
    if p["launcher"].is_file():
        ok.append("launcher")
    else:
        errors.append("missing launcher")
    if (p["eac_dir"] / "Settings.json").is_file():
        ok.append("EAC Settings.json")
    else:
        errors.append("missing EAC Settings.json")
    if p["game_log"].exists():
        ok.append(f"Game.log {p['game_log'].stat().st_size} bytes")
    else:
        ok.append("Game.log not present yet (ok if you have not played)")

    py = Path(sys.executable)
    if "WindowsApps" in str(py):
        errors.append(f"python is the WindowsApps stub: {py}")
    else:
        ok.append(f"python {sys.version.split()[0]} {py}")

    pktmon = Path(r"C:\Windows\system32\PktMon.exe")
    if pktmon.is_file():
        ok.append("pktmon")
    else:
        errors.append("pktmon missing")

    print(json.dumps({"ok": ok, "errors": errors}, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
