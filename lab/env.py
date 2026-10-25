"""Process environment for lab children.

Rust's MinGW/OpenSSL PATH rewrite is not applied here. The Python world uses
pyOpenSSL and must not inherit a compiler toolchain PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from lab.paths import ROOT, TMP

PS = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]
WINDOWS_HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def launcher_shell() -> str:
    """PowerShell that can run Start-NwPrivate.ps1.

    Measured 2026-10-14: Windows PowerShell 5.1 on this machine loads
    Microsoft.PowerShell.Utility but does not expose Get-FileHash, so the
    launcher died before the game window appeared. PowerShell 7 does.
    """
    return shutil.which("pwsh") or "powershell.exe"


def app_python() -> str:
    """Repo-local interpreter after setup, otherwise the one running ef.py."""
    candidate = ROOT / ".azoth" / "venv" / "Scripts" / "python.exe"
    return str(candidate) if candidate.is_file() else sys.executable


def local_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Keep subprocess scratch files in the checkout, not the user temp."""
    TMP.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = str(TMP)
    env["TMP"] = str(TMP)
    env["PIP_CACHE_DIR"] = str(ROOT / ".azoth" / "cache" / "pip")
    if overrides:
        env.update(overrides)
    return env
