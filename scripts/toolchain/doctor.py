#!/usr/bin/env python3
"""Print a contributor readiness checklist (tools, Rust, OpenSSL). Exit 1 if core gaps."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".azoth"
DEPLOY_CADDY = ROOT / "deploy" / "bin" / "caddy.exe"


def _ok(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  OK   {label}{suffix}")


def _bad(label: str, fix: str) -> None:
    print(f"  MISS {label}")
    print(f"       fix: {fix}")


def _warn(label: str, detail: str) -> None:
    print(f"  WARN {label} — {detail}")


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=ROOT)
    except OSError as exc:
        return 1, str(exc)
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out


def check_python() -> bool:
    venv = LOCAL / "venv" / ("Scripts" if sys.platform == "win32" else "bin") / (
        "python.exe" if sys.platform == "win32" else "python"
    )
    if venv.is_file():
        code, out = _run([str(venv), "--version"])
        if code == 0:
            _ok("project venv Python", out)
            return True
    _bad("project venv Python", "python ef.py setup --core")
    return False


def check_caddy() -> bool:
    if DEPLOY_CADDY.is_file():
        _ok("Caddy", str(DEPLOY_CADDY.relative_to(ROOT)))
        return True
    if shutil.which("caddy"):
        _ok("Caddy", "on PATH")
        return True
    _bad("Caddy", "python ef.py setup --core")
    return False


def check_re() -> None:
    ghidra = LOCAL / "tools" / "ghidra"
    jdk = LOCAL / "tools" / "jdk"
    if ghidra.is_dir() and jdk.is_dir():
        _ok("RE toolchain (Ghidra+JDK)")
    else:
        _warn("RE toolchain", "optional; python ef.py setup --re")


def check_rust() -> None:
    code, out = _run(["cargo", "--version"])
    if code != 0:
        _warn("cargo / Rust", "not required until a meaning card allows server/. See docs/PLAN.md")
        return
    _ok("cargo", out.splitlines()[0] if out else "cargo")
    rustc_host = ""
    code, out = _run(["rustc", "-vV"])
    if code == 0:
        for line in out.splitlines():
            if line.startswith("host:"):
                rustc_host = line.split(":", 1)[1].strip()
                _ok("rustc host", rustc_host)
                break
    if "msvc" in rustc_host and not shutil.which("link.exe"):
        _bad(
            "MSVC linker",
            "rustc is *-windows-msvc but link.exe is missing — install "
            "Visual Studio Build Tools (C++ workload), or `rustup default "
            "stable-x86_64-pc-windows-gnu` and use MinGW OpenSSL only",
        )
        return
    return


def check_git_clean_hints() -> None:
    if (ROOT / "private-client").exists():
        _ok("private-client/ present (gitignored)")
    else:
        _warn("private-client/", "created by game setup when you copy the client")


def main() -> int:
    print("Everfall doctor (lab checklist)")
    print(f"root: {ROOT}")
    print()
    print("Core (Python lab)")
    core_ok = True
    core_ok &= check_python()
    core_ok &= check_caddy()
    print()
    print("Optional")
    check_rust()
    check_re()
    check_git_clean_hints()
    print()
    print("Logs live under .azoth/logs/ after `python ef.py dev`.")
    print("Current step: STATUS.md")
    print("Purge local tools: python ef.py setup --purge")
    if not core_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
