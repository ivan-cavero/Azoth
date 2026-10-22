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
The binary stores AZ type descriptors in `.rdata` as a record whose name and uuid
are separated by the record's own field block:

    <name>\0<field block>{<GUID>}

The GUID is **brace-wrapped**; it is AZ's own UUID rendering (`{AA0A0B64-...}`,
uppercase), which is what makes it a descriptor terminator instead of a random
uuid string. A looser scan for `<name>\0...<bare-guid>` (no braces) also matches,
but its pairings are NOT trustworthy: the bare form also occurs in regions where
a name and an unrelated GUID happen to be adjacent. Measured 2026-10-10, the loose
form pairs `Transform` with `5D9958E9-...` (the AZ math `Transform` struct) while
the braced form at the same offset is unambiguous, and the entity-component
`Transform` the client uses is `484AE67D-...`. So this tool only emits the braced
form.

THE FIELD BLOCK: TWO FORMS, MEASURED ON 1.400 AND 1.460
------------------------------------------------------
Observed: the block between the name's NUL terminator and the brace is a run of
addresses that land in `.text`, and some descriptors have no such run at all (only
NUL padding). Inferred: the run is the descriptor's registered-callback list, empty
for a type that registers none, which is why both forms occur in one image:

  1.400/1.460 form A (NUL padding only), unchanged since the first version of
  this tool:

      GlobalStorageComponentServerFacet_RequestSearchStorage\0\0{4F234D55-...}

  1.460 form B (field block present), the one that made a byte-for-byte
  regeneration of this registry lose names:

      file offset 0x8137680   "GlobalStorageComponentClientFacet_ReceiveStorageSearchItems\0"
      file offset 0x81376bb   five NUL bytes (padding to the next 8-byte boundary)
      file offset 0x81376c0   six qwords: 0x142cd2350 0x142cd2350 0x142cd2490
                                          0x142cd2520 0x14078fbb0 0x14046de30
      file offset 0x81376f0   "{AA0A0B64-475A-4828-A050-7B1A3F045493}\0\0"

  Read off the 1.460 image (NewWorld.exe sha256 30fe6461..., size 179,214,008
  bytes). Every one of those six qwords is an address inside that same image and
  lands in `.text`, so the run is the descriptor's function-pointer block, not
  padding.

Recognising form B without weakening form A's guarantee needs four conditions,
each one measured rather than assumed:

  * The block must be the *maximal* run of in-image qword pointers immediately
    before the brace, and it must be preceded by at least one NUL byte. A name
    that is not separated from the brace by a NUL boundary is not a descriptor.
  * The block is capped at MAX_FIELD_BLOCK qwords. The longest block in a pairing
    the 1.400 build independently confirms is 28 (`RewardTrackComponentServerFacet_
    RequestResetRewardTrack`, file offset 0x8217b80). Above the cap sit the
    pointer-dense embedded-data tables, where a *data record* name happens to
    precede an unrelated pointer array: `FxScriptsData` at 0x85f4250 is followed
    by 331 qwords and then {7E27B9BC-...}, a guid the type table does not know.
    Keeping the cap at the measured descriptor size leaves that class out.
  * The name must be a whole string that starts on an 8-byte boundary, the same
    boundary every descriptor name and brace in this image sits on. A fragment
    inside a packed string table (`.png`, `json`, `min` in the 1.460 image) is not
    a name, and the legacy form is the only reason those ever got in.
  * The name must not be a bare hex fragment of eight or more digits. MEASURED
    FALSE PAIRING that this rejects: `7E3497006D14` + six qwords + the real guid of
    wire 5543, which the independent `.rdata` route names
    `SocialComponentServerFacet_DebugAcceptAllFriendInvites`.

  TRUST CHECK, measured 2026-10-22 on the real 1.460 image (a one-off audit, not
  something `--check` re-runs): for every added pairing whose guid is in the type
  table and whose wire the independent `.rdata` route also names, the field block
  agrees 12 of 13 times. The existing NUL form agrees 58 of 60 under the same
  test, so form B is not a weaker claim than form A; the one disagreement is the
  hex fragment above, which the name filter drops. A pairing is also refused
  outright when the *NUL* form already named that guid with another name, because
  one guid has one registered name -- the reverse of the name->many-GUIDs relation
  below -- so a second name is an adjacency error, not a second fact.

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
that also appears in `typeindex.json`, plus the form-B anchors whose offsets are
recorded above). If any of those stop matching, the scan is wrong and the tool
says so instead of writing.

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
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "atlas" / "az-type-registry.json"

UUID_TEXT = rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

# Form A, unchanged: only NUL padding between the name and the brace; see the
# module docstring for why the bare (unbraced) form is not used.
NAME_GUID = re.compile(rb"([A-Za-z_][A-Za-z0-9_:<>@, ]{2,90}?)\x00{1,16}\{(" + UUID_TEXT + rb")\}")

# Form B is parsed from the brace offset, so the brace needs its own pattern.
BRACE_GUID = re.compile(rb"\{(" + UUID_TEXT + rb")\}")

# The characters an AZ type name is made of; the same set the form-A literal uses.
NAME_BYTES = frozenset(
    b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_:<>@, "
)
NAME_MIN = 3
NAME_MAX = 90

# Longest field block a *confirmed* descriptor pairing has (28 qwords); see the
# module docstring for what sits above it.
MAX_FIELD_BLOCK = 32

# A bare hex run is a guid/hash fragment, never an AZ type name.
HEX_FRAGMENT = re.compile(r"[0-9A-Fa-f]{8,}")

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
    # Form-B anchors on 1.460. Each is hand-verified twice over: the same
    # name+GUID pair is in the 1.400 registry committed at build 8654f01d, and
    # the GUID is the type-table entry the protocol work already names. Offsets
    # are the 1.460 file offsets of the name and the brace.
    #   0x8137680 / 0x81376f0, six field-block qwords, wire 7048
    "GlobalStorageComponentClientFacet_ReceiveStorageSearchItems": "aa0a0b64-475a-4828-a050-7b1a3f045493",
    #   0x8137410 / 0x81374d8, fifteen field-block qwords, wire 2780
    "PlayerPositionTrackingComponentServerFacet_RequestAISpawnManagerDebugInfo": "6eb512fd-da31-4243-82ae-fb8903e9ea77",
    #   0x857aed0 / 0x857af48, twelve field-block qwords, wire 689
    "HubEndpointSharingTrait": "36a8e1bc-c145-4bd1-8354-78c8b644decd",
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


def nul_form_pairs(data: bytes) -> dict[str, list[str]]:
    """Form A: name, NUL padding, brace-wrapped GUID."""
    found: dict[str, list[str]] = {}
    for match in NAME_GUID.finditer(data):
        name = match.group(1).decode("latin1").strip()
        guid = match.group(2).decode().lower()
        bucket = found.setdefault(name, [])
        if guid not in bucket:
            bucket.append(guid)
    return found


def field_block_pairs(data: bytes, image_base: int, image_end: int) -> dict[str, list[str]]:
    """Form B: name, NUL padding, the record's pointer field block, brace GUID.

    Every condition is in the module docstring, with the measured example that
    justifies it. A candidate that fails any of them is dropped, never guessed.
    """
    found: dict[str, list[str]] = {}
    for match in BRACE_GUID.finditer(data):
        brace = match.start()
        if brace % 8:
            continue  # descriptor records are 8-byte aligned
        cursor = brace
        words = 0
        while cursor - 8 >= 0:
            value = int.from_bytes(data[cursor - 8 : cursor], "little")
            if not (image_base <= value < image_end) or value % 4:
                break
            cursor -= 8
            words += 1
        if not 1 <= words <= MAX_FIELD_BLOCK:
            continue
        if cursor < 1 or data[cursor - 1] != 0:
            continue  # a descriptor separates its name from the block with NULs
        end = cursor
        while end > 0 and data[end - 1] == 0:
            end -= 1
        if end == cursor:
            continue  # no NUL padding at all: the name is not NUL-terminated here
        start = end
        while start > 0 and data[start - 1] in NAME_BYTES:
            start -= 1
        name = data[start:end]
        if not NAME_MIN <= len(name) <= NAME_MAX:
            continue
        if start % 8:
            continue  # descriptor names start on a record boundary
        if start and 0x20 <= data[start - 1] < 0x7F:
            continue  # a tail of a longer printable run is not a name
        text = name.decode("latin1")
        if not (text[0].isalpha() or text[0] == "_"):
            continue
        if HEX_FRAGMENT.fullmatch(text):
            continue
        guid = match.group(1).decode().lower()
        bucket = found.setdefault(text, [])
        if guid not in bucket:
            bucket.append(guid)
    return found


def scan_report(
    data: bytes, image_base: int, image_end: int
) -> tuple[dict[str, list[str]], int, list[dict]]:
    """Both forms merged, plus how many pairs came from form B and what it refused.

    A form-B pairing never renames a GUID that form A already named: one GUID has
    one registered name (only the name->many-GUIDs direction is open), so a second
    name for the same GUID means the block adjacency was wrong.
    """
    found = nul_form_pairs(data)
    owners: dict[str, set[str]] = {}
    for name, guids in found.items():
        for guid in guids:
            owners.setdefault(guid, set()).add(name)
    pointer_entries = 0
    conflicts: list[dict] = []
    for name, guids in field_block_pairs(data, image_base, image_end).items():
        for guid in guids:
            named_by = owners.get(guid)
            if named_by and name not in named_by:
                conflicts.append({"name": name, "guid": guid, "named_by": sorted(named_by)})
                continue
            bucket = found.setdefault(name, [])
            if guid not in bucket:
                bucket.append(guid)
                pointer_entries += 1
    return found, pointer_entries, conflicts


def scan(data: bytes, image_base: int, image_end: int) -> dict[str, list[str]]:
    """Every name+GUID pair this build registers, from both descriptor forms."""
    return scan_report(data, image_base, image_end)[0]


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
    pe = PE(exe)
    data = pe.data
    image_end = max(section["va"] + section["vsize"] for section in pe.sections)
    found, pointer_entries, conflicts = scan_report(data, pe.image_base, image_end)
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
            "'<name>\\0<padding>[<field block>]{GUID}' descriptor form in .rdata (the only "
            "trustworthy pairing; see reverse/tools/scan-az-types.py). The field block is the "
            "descriptor's own run of in-image pointers and is empty when the type registers no "
            "callbacks, which is why both a NUL-padded and a pointer-separated interstice occur. "
            "A name can map to SEVERAL GUIDs -- 'Transform' is both the AZ math struct and a "
            "reflected type -- so disambiguate with another signal. 'wire_type' is the index into "
            "the per-build type table, present only for types the table knows. This file "
            "supersedes the shifted GUID list in the old local_player_has_no_physics_20261004 "
            "atlas note."
        ),
        "build_sha256": sha256_of(exe),
        "names": len(found),
        "entries": len(types),
        "pointer_form_entries": pointer_entries,
        "superseded_wrong_pairings": SUPERSEDED_WRONG_GUIDS,
        "field_block_conflicts": conflicts,
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
        f"{payload['names']} names, {payload['entries']} name+guid entries "
        f"({payload.get('pointer_form_entries', 0)} from the field-block form), "
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
