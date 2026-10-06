#!/usr/bin/env python3
"""Inspect EAC EOS files on disk. No bypass, no memory, no inject."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths, write_json  # noqa: E402


def inspect() -> dict:
    p = default_paths()
    eac = p["eac_dir"]
    settings = {}
    sp = eac / "Settings.json"
    if sp.exists():
        raw = sp.read_text(encoding="utf-8", errors="replace")
        # Settings.json is space-padded; json.loads still accepts it.
        try:
            settings = json.loads(raw)
        except json.JSONDecodeError:
            settings = {"raw_head": raw[:500]}
    roaming = p["eac_roaming"]
    logs = []
    if roaming.exists():
        for f in roaming.rglob("*"):
            if f.is_file():
                logs.append({"path": str(f), "bytes": f.stat().st_size})
    return {
        "install_eac": str(eac),
        "settings": settings,
        "productid": settings.get("productid"),
        "sandboxid": settings.get("sandboxid"),
        "deploymentid": settings.get("deploymentid"),
        "protected_exe": settings.get("executable"),
        "roaming_logs": logs,
        "policy": [
            "EAC EOS loads a kernel driver plus a DLL inside NewWorld.exe.",
            "ObRegisterCallbacks strips PROCESS_VM_READ and PROCESS_VM_WRITE.",
            "Live process memory read trips the same sensor as a write.",
            "This script only reads Settings.json and local logs on disk.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect EAC files on disk")
    ap.add_argument("--out")
    args = ap.parse_args()
    info = inspect()
    p = default_paths()
    out = Path(args.out) if args.out else p["research"] / "sessions" / "eac_inspect.json"
    write_json(out, info)
    print(
        json.dumps(
            {
                k: info[k]
                for k in ("productid", "sandboxid", "deploymentid", "protected_exe")
            },
            indent=2,
        )
    )
    print(f"local EAC logs: {len(info['roaming_logs'])}")
    print(f"wrote {out}")
    print("See docs/EAC.md — no bypass here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
