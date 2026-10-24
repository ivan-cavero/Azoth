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
    _bad("project venv Python", "python az.py setup --core")
    return False


def check_caddy() -> bool:
    if DEPLOY_CADDY.is_file():
        _ok("Caddy", str(DEPLOY_CADDY.relative_to(ROOT)))
        return True
    if shutil.which("caddy"):
        _ok("Caddy", "on PATH")
        return True
    _bad("Caddy", "python az.py setup --core")
    return False


def check_re() -> None:
    ghidra = LOCAL / "tools" / "ghidra"
    jdk = LOCAL / "tools" / "jdk"
    if ghidra.is_dir() and jdk.is_dir():
        _ok("RE toolchain (Ghidra+JDK)")
    else:
        _warn("RE toolchain", "optional; python az.py setup --re")


def check_rust() -> bool:
    code, out = _run(["cargo", "--version"])
    if code != 0:
        _bad("cargo / Rust", "https://rustup.rs — needed for server/")
        return False
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
        return False
    return True


def check_openssl() -> bool:
    """Enough signal to build azoth-dtls; not a full compile."""
    if sys.platform == "win32":
        # Apply the same PATH/OPENSSL_DIR fixes az.py uses for cargo.
        env = os.environ.copy()
        try:
            import rust_openssl_env as roe  # type: ignore
        except ImportError:
            import importlib.util

            helper = Path(__file__).resolve().parent / "rust_openssl_env.py"
            spec = importlib.util.spec_from_file_location("rust_openssl_env", helper)
            assert spec and spec.loader
            roe = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(roe)
        notes = roe.apply(env)
        for note in notes:
            if "without link.exe" in note or "must not use MinGW" in note:
                _bad("Rust / OpenSSL stack", note)
                return False
            if "no MSYS2" in note:
                _bad("Rust / OpenSSL stack", note)
                return False
            _ok("Rust / OpenSSL stack", note)

        rustc_host = roe.rustc_host()
        if "gnu" in rustc_host:
            gcc = roe.which_gcc(env)
            if not gcc:
                _bad("gcc for GNU rustc", "MSYS2 mingw64 gcc on PATH")
                return False
            if "brechtsanders" in gcc.casefold() or "winlibs" in gcc.casefold():
                _bad(
                    "mixed MinGW",
                    f"gcc resolves to WinLibs ({gcc}); MSYS2 must win. "
                    "Use `python az.py cargo …` or put C:\\msys64\\mingw64\\bin first.",
                )
                return False
            _ok("gcc", gcc)
            openssl_dir = env.get("OPENSSL_DIR", "")
            if openssl_dir and (Path(openssl_dir) / "include" / "openssl" / "ssl.h").is_file():
                _ok("OpenSSL (MSYS)", openssl_dir)
                return True
            _bad("OpenSSL headers", "expected include/openssl/ssl.h under OPENSSL_DIR")
            return False

        vcpkg = env.get("VCPKG_ROOT") or env.get("VCPKG_INSTALLATION_ROOT")
        openssl_dir = env.get("OPENSSL_DIR") or env.get("OPENSSL_LIB_DIR")
        if openssl_dir and Path(openssl_dir).exists():
            _ok("OpenSSL hint", f"OPENSSL_* → {openssl_dir}")
            return True
        if vcpkg and Path(vcpkg).is_dir():
            _ok("vcpkg root", vcpkg)
            _warn(
                "OpenSSL package",
                "ensure `vcpkg install openssl:x64-windows` (MSVC rustc) — see ADR 0004",
            )
            return True
        _bad(
            "OpenSSL for Windows Rust link",
            "MSVC: vcpkg openssl + VCPKG_ROOT; GNU: MSYS2 mingw64. ADR 0004.",
        )
        return False

    code, out = _run(["pkg-config", "--modversion", "openssl"])
    if code == 0:
        _ok("OpenSSL (pkg-config)", out)
        return True
    _bad(
        "OpenSSL headers",
        "Debian/Ubuntu: sudo apt install libssl-dev pkg-config; "
        "Fedora: sudo dnf install openssl-devel",
    )
    return False


def check_git_clean_hints() -> None:
    if (ROOT / "private-client").exists():
        _ok("private-client/ present (gitignored)")
    else:
        _warn("private-client/", "created by game setup when you copy the client")


def main() -> int:
    print("Azoth doctor (contributor checklist)")
    print(f"root: {ROOT}")
    print()
    print("Core (server / web loop)")
    core_ok = True
    core_ok &= check_python()
    core_ok &= check_caddy()
    core_ok &= check_rust()
    print()
    print("DTLS build")
    ssl_ok = check_openssl()
    print()
    print("Optional")
    check_re()
    check_git_clean_hints()
    print()
    print("Logs live under .azoth/logs/ after `python az.py dev`.")
    print("Contributor loop: docs/runbooks/contributor-loop.md")
    print("Purge local tools: python az.py setup --purge")
    if not core_ok:
        return 1
    if not ssl_ok:
        # Core stack can still run Python prototype; Rust world needs OpenSSL.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
