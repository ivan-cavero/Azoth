#!/usr/bin/env python3
"""Snapshot install files and PAK indexes. Disk only."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths, ensure_dir, utc_now, write_json  # noqa: E402


def sha256(path: Path, cap: int | None = None) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
            if cap and n >= cap:
                break
    return h.hexdigest()


def pak_summary(pak: Path, limit_names: int = 12) -> dict:
    info: dict = {"path": str(pak), "bytes": pak.stat().st_size if pak.exists() else 0}
    if not pak.exists():
        info["error"] = "missing"
        return info
    try:
        with zipfile.ZipFile(pak) as z:
            names = z.namelist()
            ext = Counter(Path(n).suffix.lower() or "(none)" for n in names)
            info["entries"] = len(names)
            info["ext"] = ext.most_common(12)
            info["sample"] = names[:limit_names]
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        with pak.open("rb") as f:
            info["magic"] = f.read(8).hex()
    return info


def copy_tree_files(src: Path, dst: Path, names: list[str]) -> list[str]:
    copied = []
    for name in names:
        s = src / name
        if s.is_file():
            ensure_dir(dst)
            shutil.copy2(s, dst / name)
            copied.append(name)
    return copied


def run(out: Path, hash_exe: bool) -> Path:
    p = default_paths()
    ensure_dir(out)
    install = p["install"]
    meta = {
        "utc": utc_now(),
        "install": str(install),
        "install_exists": install.exists(),
        "exe_exists": p["exe"].exists(),
        "exe_bytes": p["exe"].stat().st_size if p["exe"].exists() else 0,
        "launcher_bytes": p["launcher"].stat().st_size if p["launcher"].exists() else 0,
    }
    if hash_exe:
        print("SHA-256 NewWorld.exe (lento)...")
        meta["exe_sha256"] = sha256(p["exe"])

    files_dir = ensure_dir(out / "files")
    copy_tree_files(
        install,
        files_dir,
        [
            "bootstrap.cfg",
            "engine.json",
            "PaksList.lst",
            "system_windows_pc.cfg",
            "typeindex.json",
        ],
    )
    if (install / "assets" / "Config" / "Game.xml").exists():
        ensure_dir(files_dir / "Config")
        shutil.copy2(
            install / "assets" / "Config" / "Game.xml",
            files_dir / "Config" / "Game.xml",
        )
    eac_src = p["eac_dir"]
    if eac_src.exists():
        copy_tree_files(eac_src, files_dir / "EasyAntiCheat", ["Settings.json"])

    ags = ensure_dir(out / "ags")
    for folder, tag in ((p["ags_local"], "local"), (p["ags_roaming"], "roaming")):
        if folder.exists():
            dest = ensure_dir(ags / tag)
            for f in folder.rglob("*"):
                if f.is_file() and f.stat().st_size < 8_000_000:
                    rel = f.relative_to(folder)
                    target = dest / rel
                    ensure_dir(target.parent)
                    shutil.copy2(f, target)

    paks = []
    assets = install / "assets"
    if assets.exists():
        for pak in sorted(assets.glob("*.pak"))[:8]:
            print(f"PAK {pak.name}...")
            paks.append(pak_summary(pak))
        level = assets / "levels" / "newworld_vitaeeterna" / "level.pak"
        if level.exists():
            paks.append(pak_summary(level))
    write_json(out / "paks.json", paks)
    write_json(out / "disk.json", meta)
    print(f"OK disk -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="On-disk snapshot of the New World install"
    )
    ap.add_argument("--out", help="output directory")
    ap.add_argument("--hash-exe", action="store_true")
    args = ap.parse_args()
    p = default_paths()
    out = Path(args.out) if args.out else p["repo"] / "sessions" / "disk_snapshot"
    run(out, args.hash_exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
