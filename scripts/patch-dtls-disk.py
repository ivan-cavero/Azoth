#!/usr/bin/env python3
"""Apply the verified DTLS verify bypass to the private executable copy only.

The launcher keeps NewWorld.exe as an independent file in the repo-local
private runtime. This helper patches that copy on disk; it never writes the
Steam installation.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reverse" / "tools"))
from catalog import PE  # noqa: E402

PATCH_VA = 0x145DCE8B5
ORIGINAL = bytes.fromhex("0f8419010000")


def paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[1]
    private = root / "private-client" / "runtime" / "Bin64" / "NewWorld.exe"
    install = Path(
        os.environ.get(
            "AZOTH_GAME_INSTALL",
            r"C:\Program Files (x86)\Steam\steamapps\common\New World",
        )
    )
    official = install / "Bin64" / "NewWorld.exe"
    if not official.is_file():
        raise SystemExit(f"official executable not found: {official}")
    return private, official


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def patch(private: Path, official: Path) -> None:
    if not private.parent.is_dir():
        raise SystemExit(f"private runtime directory not found: {private.parent}")
    if not private.exists():
        raise SystemExit(f"private executable not found: {private}")

    target = PATCH_VA + 6 + struct.unpack_from("<i", ORIGINAL, 2)[0]
    rel = target - (PATCH_VA + 5)
    patched = b"\xe9" + struct.pack("<i", rel) + b"\x90"

    if digest(private) != digest(official):
        # Idempotent: a copy that already carries the patch is not an error.
        pe = PE(private)
        offset = pe.va_to_foff(PATCH_VA)
        with private.open("rb") as f:
            f.seek(offset)
            if f.read(len(patched)) == patched:
                print(f"private DTLS patch already applied: {private}")
                print(f"sha256(private)={digest(private)}")
                return
        raise SystemExit("private executable is not the verified Steam copy; refusing implicit overwrite")
    private.unlink()
    shutil.copyfile(official, private)

    pe = PE(private)
    offset = pe.va_to_foff(PATCH_VA)
    with private.open("r+b") as f:
        f.seek(offset)
        before = f.read(len(ORIGINAL))
        if before != ORIGINAL:
            raise SystemExit(f"unexpected bytes at {PATCH_VA:#x}: {before.hex()}")
        f.seek(offset)
        f.write(patched)
    print(f"private DTLS patch applied: {private}")
    print(f"official source unchanged: {official}")
    print(f"sha256(after private patch)={digest(private)}")


def restore(private: Path, official: Path) -> None:
    if private.exists():
        private.unlink()
    shutil.copyfile(official, private)
    print(f"private executable restored from official copy: {private}")
    print(f"official source unchanged: {official}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("apply", "restore", "check"))
    args = ap.parse_args()
    private, official = paths()
    if args.action == "apply":
        patch(private, official)
    elif args.action == "restore":
        restore(private, official)
    else:
        print(f"private={private} exists={private.exists()}")
        print(f"official={official} sha256={digest(official)}")
        if private.exists():
            print(f"private_sha256={digest(private)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
