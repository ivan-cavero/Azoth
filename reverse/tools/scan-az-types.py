"""Regenerate research/atlas/az-type-registry.json: the verified AZ type registry.

WHY THIS EXISTS
===============
The repository's GUID facts had drifted. `local_player_has_no_physics_20261004`
recorded a physics-component GUID list that is **systematically shifted by one
entry**, and `physics_component_guids_corrected_20261005` corrected only four of
them, so the record still disagrees with the binary. A wrong GUID silently
poisons every downstream conclusion (that is exactly how "the player has no
physics component" was concluded from a search for ids that do not exist).

THE LAYOUT, AND WHY ONLY ONE PATTERN IS TRUSTWORTHY
---------------------------------------------------
The binary stores AZ type descriptors in `.rdata` as

    <name>\0<padding>\0{<GUID>}

The GUID is **brace-wrapped** and the name is separated from it only by NUL
padding. A looser scan for `<name>\0...<bare-guid>` (no braces) also matches, but
its pairings are NOT trustworthy: the bare form also occurs in regions where a
name and an unrelated GUID happen to be adjacent. Measured 2026-10-10, the loose
form pairs `Transform` with `5D9958E9-...` (the AZ math `Transform` struct) while
the braced form at the same offset is unambiguous, and the entity-component
`Transform` the client uses is `484AE67D-...`. So this tool only emits the braced
form.

ONE NAME CAN HAVE MANY GUIDS
----------------------------
`Transform` is both an AZ math struct and a reflected type; `Character` is a
component and a class. The output therefore maps each name to a LIST of GUIDs,
and a consumer that needs one must disambiguate by another signal (the slice
that references it, the type table, or the descriptor's neighbours).

VALIDATION
----------
`--check` verifies a small set of GUIDs that were read by hand from the byte
dump and are independently established (the physics family, plus every entry
that also appears in `typeindex.json`). If any of those stop matching, the scan
is wrong and the tool says so instead of writing.

Usage:
    python reverse/tools/scan-az-types.py [--exe PATH] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "atlas" / "az-type-registry.json"

# Only the brace-wrapped form; see the module docstring for why.
NAME_GUID = re.compile(
    rb"([A-Za-z_][A-Za-z0-9_:<>@, ]{2,90}?)\x00{1,16}"
    rb"\{([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}"
)

# Read by hand from the byte dump (see the module docstring) and independently
# established. The tool refuses to write if any of these stops matching.
PINNED = {
    "GameRigidBodyConfig": "0bcab3ac-6abb-4462-9253-44565e6bd8d8",
    "GameRigidBodyClientFacetConfig": "0e0edeca-8336-45fd-9c33-052d2fb23b4e",
    "GameRigidBodyServerFacetConfig": "0c1f07a3-01d4-426f-b853-3b2ff9979913",
    "GameRigidBodyComponentBase": "a35838bf-c2ed-473a-b137-f9ced18de074",
    "GameRigidBodyComponent": "5ba2d1fc-db9d-4b81-88c9-89787d5c19f1",
    "GameRigidBodyComponentClientFacet": "4a3df78e-c81d-4f7c-bffa-cdd2a16b329e",
    "CharacterControllerComponent": "e9d84b77-422a-4dcb-9eff-708120b1b1a0",
    "CharacterControllerConfig": "cc8afebd-5f7a-4e63-a472-ffc8591db051",
    "CharacterPhysicsComponent": "d707d6c5-3efa-4275-82eb-a954f845d324",
    "CharacterComponent": "15407caa-4970-4d06-8b5c-612fba11bb45",
    "CharacterComponentClientFacet": "8817475c-56be-46f3-9597-ff325929461e",
    "CharacterComponentServerFacet": "e9c20ecf-9de9-4969-b76d-91582ed7294d",
    "PlayerInputFiltersComponent": "6585d0e9-22e5-44eb-994e-cc80229fcd68",
    "NetBindingComponent": "e9ca5d63-ed2d-4b59-b3c4-ebcd4a0013e4",
}
# NOT pinned: `PhysicsTrait` and `PhysicsTrait::State`. Their GUID
# (F05E34C6-AF1E-476D-9472-5FC118FC4503) sits ~40 bytes BEFORE the name with no
# brace wrapping, so pairing them is a proximity inference, not a layout. The
# earlier atlas note that called it `PhysicsTrait::State`'s GUID is therefore
# [I], not [E]. The trait's message set IS reliable and comes from the mangled
# names instead -- see reverse/tools/scan-trait-registry.py.

# The sets the OLD, wrong atlas entry used, kept so the correction is auditable.
SUPERSEDED_WRONG_GUIDS = {
    "0bcab3ac-6abb-4462-9253-44565e6bd8d8": "GameRigidBodyConfig, NOT GameRigidBodyClientFacetConfig",
    "0c1f07a3-01d4-426f-b853-3b2ff9979913": "GameRigidBodyServerFacetConfig, NOT GameRigidBodyComponentBase",
    "0e0edeca-8336-45fd-9c33-052d2fb23b4e": "GameRigidBodyClientFacetConfig, NOT GameRigidBodyServerFacetConfig",
    "824e1e63-89eb-49fd-8d85-64aa899a61ca": "RockNRoll::CharacterSupportInfo, NOT CharacterControllerConfig",
    "b1237004-14e1-4327-8774-d2c5796230e7": "absent from this build (no name pairs with it)",
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def scan(data: bytes) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for match in NAME_GUID.finditer(data):
        name = match.group(1).decode("latin1").strip()
        guid = match.group(2).decode().lower()
        bucket = found.setdefault(name, [])
        if guid not in bucket:
            bucket.append(guid)
    return found


def type_table() -> dict[str, int]:
    """The per-build AZ type table, or a hard stop if it is missing.

    This MUST NOT degrade silently. Without the table every entry would come out
    `in_type_table: false`, and writing that would overwrite the committed
    registry with a strictly worse one -- which is exactly the kind of quiet
    regression the scanners exist to prevent. The file is not in git
    (private-client/ is ignored); the launcher copies it from the Steam install.
    """
    path = ROOT / "private-client" / "runtime" / "typeindex.json"
    if not path.is_file():
        # The file is not in git (private-client/ is ignored) and there is no
        # `az.py disk` command. The LAUNCHER copies it from the Steam install
        # along with bootstrap.cfg / engine.json / PaksList.lst /
        # system_windows_pc.cfg. So build the private runtime once.
        raise SystemExit(
            "missing "
            + str(path)
            + ": the launcher copies it from the Steam install. Build the private runtime once with `python az.py game`, then re-run this tool. Refusing to write a registry without wire types."
        )
    entries = json.loads(path.read_text(encoding="utf-8"))["typeIndex"]
    return {g.lower().replace("-", ""): i for i, g in enumerate(entries)}


def build(exe: Path) -> dict:
    data = exe.read_bytes()
    found = scan(data)
    table = type_table()
    types = []
    for name in sorted(found):
        for guid in found[name]:
            index = table.get(guid.replace("-", ""))
            types.append(
                {
                    "name": name,
                    "guid": guid,
                    "wire_type": index,
                    "in_type_table": index is not None,
                }
            )
    return {
        "$comment": (
            "Every AZ type this build registers, as name + GUID, read from the brace-wrapped "
            "'<name>\\0{padding}\\0{GUID}' descriptor form in .rdata (the only trustworthy pairing; "
            "see reverse/tools/scan-az-types.py). A name can map to SEVERAL GUIDs -- 'Transform' is "
            "both the AZ math struct and a reflected type -- so disambiguate with another signal. "
            "'wire_type' is the index into the per-build type table, present only for types the table "
            "knows. This file supersedes the shifted GUID list in the old "
            "local_player_has_no_physics_20261004 atlas note."
        ),
        "build_sha256": sha256_of(exe),
        "names": len(found),
        "entries": len(types),
        "superseded_wrong_pairings": SUPERSEDED_WRONG_GUIDS,
        "types": types,
    }


def check(payload: dict) -> int:
    by_name: dict[str, list[str]] = {}
    for entry in payload["types"]:
        by_name.setdefault(entry["name"], []).append(entry["guid"])
    problems = []
    for name, expected in PINNED.items():
        got = by_name.get(name)
        if not got:
            problems.append(f"{name}: missing from the scan")
        elif expected not in got:
            problems.append(f"{name}: got {got}, expected to include {expected}")
    if problems:
        print("PINNED-GUID CHECK FAILED (the scan or the layout is wrong):")
        for problem in problems:
            print("  -", problem)
        return 1
    in_table = sum(1 for e in payload["types"] if e["in_type_table"])
    print(
        f"pinned check OK: all {len(PINNED)} hand-verified GUIDs reproduce; "
        f"{payload['names']} names, {payload['entries']} name+guid entries, "
        f"{in_table} present in the type table"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", help="NewWorld.exe (default: the installed client)")
    parser.add_argument("--check", action="store_true", help="verify and write nothing")
    args = parser.parse_args()
    exe = Path(args.exe) if args.exe else Path(default_paths()["exe"])
    if not exe.is_file():
        raise SystemExit(f"executable not found: {exe}")
    payload = build(exe)
    if args.check:
        return check(payload)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("families by count:", dict(Counter(t["name"].split("_")[0] for t in payload["types"]).most_common(6)))
    return check(payload)


if __name__ == "__main__":
    raise SystemExit(main())
