#!/usr/bin/env python3
"""One coherent Windows Rust + OpenSSL stack for azoth-dtls.

Measured failure mode on this project: GNU rustc + WinLibs gcc on PATH while
OPENSSL_DIR points at MSYS2 mingw64 (or the reverse) → crt2.o undefined
`_gnu_exception_handler`. OpenSSL itself is fine; the two MinGW trees are not.

This module mutates an env dict: prefer MSYS2 mingw64 for both the linker and
OpenSSL when rustc is `*-windows-gnu`, and never leave WinLibs ahead of it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def rustc_host() -> str:
    try:
        proc = subprocess.run(
            ["rustc", "-vV"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    return ""


def _msys_mingw_root() -> Path | None:
    candidates: list[Path] = []
    for key in ("OPENSSL_DIR", "OPENSSL_ROOT_DIR"):
        raw = os.environ.get(key, "").strip()
        if raw:
            candidates.append(Path(raw))
    candidates.extend(
        [
            Path(r"C:\msys64\mingw64"),
            Path(r"C:\msys64\ucrt64"),
            Path(os.path.expandvars(r"%USERPROFILE%\msys64\mingw64")),
        ]
    )
    for root in candidates:
        if (root / "include" / "openssl" / "ssl.h").is_file() and (
            root / "bin" / "gcc.exe"
        ).is_file():
            return root
    return None


def _strip_foreign_mingw(path_value: str) -> str:
    """Drop WinLibs / foreign mingw bins so MSYS gcc wins."""
    keep: list[str] = []
    for part in path_value.split(os.pathsep):
        if not part:
            continue
        folded = part.replace("/", "\\").casefold()
        if "winget\\packages\\brechtsanders" in folded:
            continue
        if "winlibs" in folded and "mingw" in folded:
            continue
        keep.append(part)
    return os.pathsep.join(keep)


def apply(env: dict[str, str]) -> list[str]:
    """Apply toolchain fixes to *env*. Returns human-readable notes."""
    notes: list[str] = []
    if os.name != "nt":
        return notes

    host = rustc_host()
    if not host:
        return notes

    if "gnu" in host:
        msys = _msys_mingw_root()
        if msys is None:
            notes.append(
                "GNU rustc but no MSYS2 mingw64 OpenSSL+gcc "
                "(expected C:\\msys64\\mingw64 with include/openssl/ssl.h)"
            )
            return notes
        env["OPENSSL_DIR"] = str(msys)
        env.pop("OPENSSL_LIB_DIR", None)
        env.pop("OPENSSL_INCLUDE_DIR", None)
        # pkg-config from a foreign tree will drag the wrong libs.
        env.pop("PKG_CONFIG_PATH", None)
        cleaned = _strip_foreign_mingw(env.get("PATH", os.environ.get("PATH", "")))
        env["PATH"] = str(msys / "bin") + os.pathsep + cleaned
        # Force the linker rustc invokes (cc crate / rustc windows-gnu).
        gcc = str(msys / "bin" / "gcc.exe")
        env["CC"] = gcc
        env["CXX"] = str(msys / "bin" / "g++.exe")
        # rustc windows-gnu invokes this for the final link (overrides PATH order).
        env["CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER"] = gcc
        notes.append(f"GNU stack: OPENSSL_DIR={msys}; linker={gcc}")
        return notes

    if "msvc" in host:
        if not shutil.which("link.exe", path=env.get("PATH")):
            notes.append(
                "MSVC rustc without link.exe — install VS Build Tools (C++) "
                "or: rustup default stable-x86_64-pc-windows-gnu"
            )
        openssl_dir = env.get("OPENSSL_DIR") or os.environ.get("OPENSSL_DIR", "")
        if openssl_dir and "mingw" in openssl_dir.replace("\\", "/").casefold():
            notes.append(
                f"MSVC rustc must not use MinGW OPENSSL_DIR={openssl_dir}; "
                "clear it and use vcpkg openssl:x64-windows"
            )
        return notes

    return notes


def which_gcc(env: dict[str, str] | None = None) -> str:
    path = (env or os.environ).get("PATH", "")
    found = shutil.which("gcc.exe", path=path) or shutil.which("gcc", path=path)
    return found or ""
