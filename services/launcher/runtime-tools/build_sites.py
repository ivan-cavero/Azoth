#!/usr/bin/env python3
"""Build-scoped patch sites and the byte check every memory patch shares.

Every VA in this directory is valid for exactly one client build (AGENTS.md:
"Identify the exact client build before relying on an address or offset").
Two rules keep a stale address out of a live process:

* a site is looked up by the SHA-256 of the executable, never by a bare global
  constant, so an unknown build stops the tool instead of patching a guess;
* every site carries the exact bytes that must be there before the write, and
  a read compares them first, so a site that moved refuses the patch instead of
  corrupting a function.

`--check` in each tool uses this module to read the private executable ON DISK
and report site, expected bytes and current bytes without starting the game.
This module only ever reads files; it never opens the game process.

Derivation history lives beside each site in the tools themselves and in
`reverse/tools/bytepat.py`, whose named anchor patterns re-derive a site from a
stable neighbouring instruction instead of from its old address.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
IMAGE_BASE = 0x140000000

# Builds whose sites this directory knows. Identity is the full SHA-256 of
# Bin64/NewWorld.exe, never a version string (research/atlas/builds.json).
BUILD_1_400 = "8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e"
BUILD_1_460 = "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033"


class Site(NamedTuple):
    """One patch site: where, what must be there, what we write, why."""

    va: int
    orig: bytes
    want: bytes
    label: str

    def detail(self) -> str:
        return (
            f"{self.label} va={self.va:#x} orig={self.orig.hex()}"
            f" want={self.want.hex()}"
        )


def private_exe() -> Path:
    return REPO / "private-client" / "runtime" / "Bin64" / "NewWorld.exe"


def official_exe() -> Path:
    install = Path(
        os.environ.get(
            "AZOTH_GAME_INSTALL",
            r"C:\Program Files (x86)\Steam\steamapps\common\New World",
        )
    )
    return install / "Bin64" / "NewWorld.exe"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_va(path: Path, va: int, n: int) -> bytes:
    """Bytes of a VA inside an executable file on disk."""
    sys.path.insert(0, str(REPO / "reverse" / "tools"))
    from catalog import PE  # noqa: E402 - local import keeps --check fast

    return PE(path).read_va(va, n)


def identify(sites: dict[str, object]) -> tuple[str, Path, str]:
    """The build hash these sites belong to, plus the exe to verify them on.

    The private runtime executable is normally the installed build plus
    `scripts/patch-dtls-disk.py`'s 6-byte DTLS edit, so its own hash is not a
    build identity. In that case the identity comes from the read-only Steam
    copy, and the per-site byte check (not the hash) is what proves the two
    copies carry the same code at the sites we are about to patch. A size
    difference is a build difference and is rejected outright.
    """
    exe = private_exe()
    if not exe.is_file():
        raise SystemExit(
            f"private runtime executable not found: {exe}\n"
            "run services/launcher/src/Start-NwPrivate.ps1 once to create it"
        )
    digest = sha256_file(exe)
    if digest in sites:
        return digest, exe, "private copy is this build, unmodified"
    official = official_exe()
    if official.is_file():
        official_digest = sha256_file(official)
        if official_digest in sites:
            if official.stat().st_size != exe.stat().st_size:
                raise SystemExit(
                    f"private runtime executable does not match the installed build:"
                    f" {exe.stat().st_size} bytes vs {official.stat().st_size}."
                    " Re-copy the private runtime before patching."
                )
            note = (
                f"private copy carries a disk patch (own sha256 {digest[:16]});"
                f" build identity {official_digest[:16]} taken from the installed copy"
            )
            return official_digest, exe, note
    known = ", ".join(sorted(k[:16] for k in sites))
    raise SystemExit(
        f"unknown client build: sha256(private)={digest}\n"
        f"known builds: {known}\n"
        "Re-derive the sites (reverse/tools/bytepat.py) before patching."
    )


def check_sites(sites: Iterable[Site], exe: Path) -> list[tuple[Site, str, bytes]]:
    """Read every site from the executable on disk and classify it.

    States: "original" (pristine, patch pending), "patched" (already carries
    `want`), "mismatch" (neither: the site moved or the build is wrong).
    """
    out: list[tuple[Site, str, bytes]] = []
    for site in sites:
        n = max(len(site.orig), len(site.want))
        cur = read_va(exe, site.va, n)
        if cur[: len(site.orig)] == site.orig:
            state = "original"
        elif cur[: len(site.want)] == site.want:
            state = "patched"
        else:
            state = "mismatch"
        out.append((site, state, cur))
    return out


def report_check(sites: dict[str, object], tool: str) -> int:
    """`--check` entry point: static site report, no process, no game."""
    digest, exe, note = identify(sites)
    table = sites[digest]
    print(f"[{tool}] build sha256={digest}")
    print(f"[{tool}] {note}")
    print(f"[{tool}] verifying {len(table)} site(s) in {exe}")
    bad = 0
    for site, state, cur in check_sites(table, exe):
        print(
            f"[{tool}] {state:9} {site.label} va={site.va:#x}"
            f" orig={site.orig.hex()} want={site.want.hex()} current={cur.hex()}"
        )
        if state == "mismatch":
            bad += 1
    if bad:
        print(f"[{tool}] FAIL: {bad} of {len(table)} site(s) do not match this build")
        return 1
    print(f"[{tool}] OK: all {len(table)} site(s) present")
    return 0


def apply_in_process(
    handle: int,
    base_addr: int,
    sites: Iterable[Site],
    revert: bool,
    tag: str,
) -> bool:
    """Patch or revert each site in a live process, checking bytes first.

    `handle` is a Win32 process handle with VM_READ|VM_WRITE|VM_OPERATION.
    Nothing is written unless the bytes at the site are exactly the expected
    ones (or already carry the requested state), so a moved site is reported
    as a failure instead of being scribbled on.
    """
    import ctypes

    k32 = ctypes.windll.kernel32
    page_readwrite = 0x04
    ok_all = True
    for site in sites:
        src, dst = (site.want, site.orig) if revert else (site.orig, site.want)
        n = max(len(src), len(dst))
        addr = ctypes.c_void_p(base_addr + (site.va - IMAGE_BASE))
        cur = ctypes.create_string_buffer(n)
        read = ctypes.c_size_t()
        if not k32.ReadProcessMemory(handle, addr, cur, n, ctypes.byref(read)):
            print(f"[{tag}] {site.va:#x} read failed: {ctypes.GetLastError()}")
            ok_all = False
            continue
        current = cur.raw[:n]
        print(f"[{tag}] {site.va:#x} ({site.label}) current: {current.hex()}")
        if current[: len(dst)] == dst:
            print("        already in the requested state")
            continue
        if current[: len(src)] != src:
            print(f"        unexpected bytes (wanted {src.hex()})")
            ok_all = False
            continue
        old = ctypes.c_ulong()
        if not k32.VirtualProtectEx(handle, addr, len(dst), page_readwrite, ctypes.byref(old)):
            print(f"        VirtualProtectEx failed: {ctypes.GetLastError()}")
            ok_all = False
            continue
        written = ctypes.c_size_t()
        done = bool(k32.WriteProcessMemory(handle, addr, dst, len(dst), ctypes.byref(written)))
        k32.VirtualProtectEx(handle, addr, len(dst), old.value, ctypes.byref(old))
        print(
            f"        {'reverted' if revert else 'patched'}"
            f"{' OK' if done else ' WRITE FAILED'}: {src.hex()} -> {dst.hex()}"
        )
        ok_all = ok_all and done
    return ok_all
