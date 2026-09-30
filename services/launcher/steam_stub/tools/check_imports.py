#!/usr/bin/env python3
"""Verify NewWorld.exe imports are covered by src/stub.def (needs `pip install pefile`)."""
from __future__ import annotations
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DEF = HERE / "src" / "stub.def"

REQUIRED = {
    "SteamAPI_Init",
    "SteamAPI_GetHSteamUser",
    "SteamAPI_RunCallbacks",
    "SteamAPI_Shutdown",
    "SteamAPI_RegisterCallback",
    "SteamAPI_UnregisterCallback",
    "SteamInternal_ContextInit",
    "SteamInternal_FindOrCreateUserInterface",
}


def read_def() -> set[str]:
    names: set[str] = set()
    for line in DEF.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith(("LIBRARY", "EXPORTS", ";", "#")):
            continue
        names.add(s.split()[0])
    return names


def read_exe_imports(exe: Path) -> set[str]:
    import pefile

    pe = pefile.PE(str(exe))
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        if e.dll.decode().lower() == "steam_api64.dll":
            return {imp.name.decode() for imp in e.imports if imp.name}
    return set()


def main() -> int:
    exported = read_def()
    missing = REQUIRED - exported
    if missing:
        print(f"FAIL stub.def missing: {sorted(missing)}");
        return 1
    print(f"OK stub.def exports {len(exported)} symbols, covers {len(REQUIRED)} required imports")
    exe_env = os.environ.get("NW_EXE", r"C:\Program Files (x86)\Steam\steamapps\common\New World\Bin64\NewWorld.exe")
    exe = Path(exe_env)
    if exe.exists():
        try:
            imports = read_exe_imports(exe)
        except ImportError:
            print("skip exe check (pip install pefile)");
            return 0
        uncovered = imports - exported
        print(f"exe imports {len(imports)}: {sorted(imports)}")
        if uncovered:
            print(f"FAIL uncovered imports: {sorted(uncovered)}")
            return 1
        print("OK all exe imports covered")
    else:
        print(f"skip exe check (not found: {exe})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
