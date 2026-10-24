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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reverse" / "tools"))
from catalog import PE  # noqa: E402

PATCH_VA = 0x145DCE8B5
ORIGINAL = bytes.fromhex("0f8419010000")

# Per-build sites for the same 6-byte JZ. The instruction itself is unchanged
# between builds (`0f 84 19 01 00 00`, patch `e9 1a 01 00 00 90`) — only its
# address moves, so this is an address table, not a byte change. The 1.460 site
# was re-derived with `python reverse/tools/bytepat.py dtls-verify` (which keys
# on the stable CMP `48 83 bf 88 02 00 00 00` that precedes it) and then read
# back: CMP at 0x145DCF9ED, JZ at 0x145DCF9F5, delta +0x1140 from 1.400.
SITES = {
    # build sha256 -> VA of the JZ
    "8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e": 0x145DCE8B5,
    "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033": 0x145DCF9F5,
}
DEFAULT_VA = 0x145DCF9F5


def paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[2]
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


def resolve_site(exe: Path) -> int:
    """The JZ address for THIS executable, keyed by its build hash.

    Falls back to DEFAULT_VA for an unknown build so that the byte check inside
    patch() is what actually guards the write, rather than a guess being trusted.
    """
    return SITES.get(digest(exe), DEFAULT_VA)

def patch(private: Path, official: Path) -> None:
    if not private.parent.is_dir():
        raise SystemExit(f"private runtime directory not found: {private.parent}")
    if not private.exists():
        raise SystemExit(f"private executable not found: {private}")

    site = resolve_site(official)
    target = site + 6 + struct.unpack_from("<i", ORIGINAL, 2)[0]
    rel = target - (site + 5)
    patched = b"\xe9" + struct.pack("<i", rel) + b"\x90"
    print(f"site for this build: {site:#x} -> patch {patched.hex()}")

    if digest(private) != digest(official):
        # Idempotent: a copy that already carries the patch is not an error.
        pe = PE(private)
        offset = pe.va_to_foff(site)
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
    offset = pe.va_to_foff(site)
    with private.open("r+b") as f:
        f.seek(offset)
        before = f.read(len(ORIGINAL))
        if before != ORIGINAL:
            raise SystemExit(
                f"unexpected bytes at {site:#x} for build {digest(official)[:16]}: {before.hex()}"
            )
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
