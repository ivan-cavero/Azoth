"""Host routing. Separate from the game launcher so neither imports the other in a cycle."""

from __future__ import annotations

import subprocess

from lab.env import PS
from lab.paths import ROOT


def mode(args: list[str]) -> int:
    action = args[0] if args else "status"
    return subprocess.call(
        [*PS, "-File", str(ROOT / "deploy" / "switch-mode.ps1"), action],
        cwd=ROOT,
    )
