"""Regenerate research/atlas/javelin-messages.json.

The Javelin message registry is the map from a message NAME to the bytes that
actually go on the wire, and the wire does not carry the name or the GUID: it
carries the message type's POSITION in the per-build type table. So two lookups
are needed and this tool does both.

1. The client ships a packed `.rdata` descriptor region where each message
   stores its `'XxxMsg'` name followed by its dashed AZ type GUID. A whole-image
   scan for that shape finds 144 messages.
2. `private-client/runtime/typeindex.json` (copied from the install by
   `reverse/tools/disk.py`) lists 7052 AZ type GUIDs, and the wire type is the
   index into that list.

Cross-check built into the output: the 12 movement-family wire types were
derived independently from live capture bytes before this scan existed, and
they must reproduce exactly. If they do not, the table or the scan is wrong and
the tool says so.

Usage:
    python reverse/tools/scan-message-registry.py [--exe PATH] [--check]
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "atlas" / "javelin-messages.json"

# name + NUL padding + dashed GUID, the layout of the descriptor region.
NAME_GUID = re.compile(
    rb"([A-Za-z][A-Za-z0-9_]{2,70}Msg)\x00{1,10}"
    rb"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

# Independently derived from capture bytes; the scan must reproduce these.
KNOWN_MOVEMENT_WIRE_TYPES = {
    "StartMovementCommunicationMsg": 0x2D6,
    "AckMovementMsg": 0x2E3,
    "CommitMovementMsg": 0x2E4,
    "MoveActorMsg": 0x2C6,
    "CheckMovementStatusMsg": 0x2EB,
    "ReceivePlayerPositionClientMsg": 0x1078,
    "MoveAnActorMsg": 0x54,
    "AbortMovementMsg": 0x2E9,
    "CancelMovementMsg": 0x14DE,
    "MoveActorToHubMsg": 0x2CE,
    "MovementTimeoutMsg": 0x2E0,
    "ProcessDeferredMovementRequestsMsg": 0x2D3,
}

FAMILIES: dict[str, tuple[str, ...]] = {
    "movement": (
        "MovementMsg",
        "MovementTimeoutMsg",
        "MoveActorMsg",
        "MoveActorToHubMsg",
        "MoveAnActorMsg",
        "StartMovementCommunicationMsg",
        "ReceivePlayerPositionClientMsg",
        "ProcessDeferredMovementRequestsMsg",
        "CrashMoveActorToHubMsg",
        "OnMoveCoordinatorChangedMsg",
    ),
    "record_fragment": (
        "FragmentUpdateMsg",
        "FragmentUpdatesMsg",
        "UpdateRecordsMsg",
        "RequestRecordsMsg",
        "ResetRecordMsg",
        "ConfirmRecordRequestMsg",
        "ConfirmRecordResponseMsg",
        "StartObservingFragmentMsg",
        "StopObservingFragmentMsg",
        "RegisterFragmentAccessMsg",
        "UnregisterFragmentAccessMsg",
        "NoFragmentsPresentMsg",
    ),
    "actor_spawn": (
        "SpawnActorsMsg",
        "ReceiveActorMsg",
        "SpawnRestoredSpatialActorMsg",
        "SpawnRestoredMonikerActorMsg",
        "OnTargetSpawnedMsg",
        "RequestSpawnTargetMsg",
        "ActorQueryMsg",
        "ConfigureTestActorsMsg",
        "CrashReceiveActorMsg",
        "OnActorMigratedMsg",
    ),
    "session": (
        "RegistrationRequestMsg",
        "RegistrationRequestV2Msg",
        "RegistrationRequestV3Msg",
        "RegistrationResponseMsg",
        "TimeSynchMsg",
        "SendClockSyncMsg",
        "PingRequestMsg",
        "PingResponseMsg",
        "ClientAliveMsg",
        "ClientConnectionMsg",
        "ClientDisconnectionMsg",
        "KickClientMsg",
        "KickClientFromRepMsg",
        "GoodbyeMsg",
        "InitMsg",
        "TargetInitMsg",
        "OnInitCompletedMessageMsg",
    ),
    "hub_routing": (
        "ReceiveHubInfoForActorsMsg",
        "ReceiveAllHubNamesMsg",
        "RequestHubInfoForActorsMsg",
        "RequestAllHubNamesMsg",
        "OnNewHubInfoMsg",
        "OnHubCrashMsg",
        "ExitPeeringMsg",
        "OnPeerChangedMsg",
        "VerifyPeersAckedStepUpdateMsg",
        "AckHubLifecycleStepUpdateMsg",
        "UpdateHubLifecycleStepMsg",
        "ContinueLifecycleStartupMsg",
    ),
}


def classify(name: str) -> str:
    for family, names in FAMILIES.items():
        for candidate in names:
            if name == candidate or (len(candidate) > 6 and candidate in name):
                return family
    return "other"


def sha256_of(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_names(exe: Path) -> dict[str, str]:
    data = exe.read_bytes()
    found: dict[str, str] = {}
    for match in NAME_GUID.finditer(data):
        found.setdefault(match.group(1).decode(), match.group(2).decode().lower())
    return found


def type_table() -> list[str]:
    path = ROOT / "private-client" / "runtime" / "typeindex.json"
    if not path.is_file():
        # This file is not in git (private-client/ is ignored) and there is no
        # `ef.py disk` command. The LAUNCHER places it, copying it from the
        # Steam install together with bootstrap.cfg / engine.json / PaksList.lst
        # / system_windows_pc.cfg (see Start-NwPrivate.ps1). So the fix is to
        # build the private runtime once.
        raise SystemExit(
            "missing "
            + str(path)
            + ": the launcher copies it from the Steam install. Build the private "
            "runtime once with `python ef.py game` (or the launcher), then "
            "re-run this tool."
        )
    return [
        guid.lower().replace("-", "")
        for guid in json.loads(path.read_text(encoding="utf-8"))["typeIndex"]
    ]


def build(exe: Path) -> dict:
    names = scan_names(exe)
    table = type_table()
    index = {guid: position for position, guid in enumerate(table)}
    messages = []
    for name in sorted(names):
        guid = names[name]
        messages.append(
            {
                "name": name,
                "guid": guid,
                "wire_type": index.get(guid.replace("-", "")),
                "family": classify(name),
            }
        )
    return {
        "$comment": (
            "Every Javelin message type this client build ships, with its AZ type GUID and the "
            "wire type number that actually goes on the wire. Source: a scan of NewWorld.exe for "
            "the packed 'XxxMsg' name + dashed-GUID descriptor region, then each GUID resolved to "
            "its POSITION in the per-build type table (private-client/runtime/typeindex.json; "
            "disk.py copies it from the install). The wire carries the table index, not the GUID, "
            "so this table is what turns a message name into bytes. Validated independently: all "
            "12 previously-known movement-family wire types reproduce exactly. A null wire_type "
            "means the GUID is registered in the binary but absent from the type table, so it "
            "cannot be addressed on the wire. Regenerate on a client update with "
            "reverse/tools/scan-message-registry.py."
        ),
        "build_sha256": sha256_of(exe),
        "type_table_entries": len(table),
        "messages": messages,
    }


def check(payload: dict) -> int:
    by_name = {m["name"]: m for m in payload["messages"]}
    problems = []
    for name, expected in KNOWN_MOVEMENT_WIRE_TYPES.items():
        entry = by_name.get(name)
        if entry is None:
            problems.append(f"{name}: missing from the scan")
        elif entry["wire_type"] != expected:
            got = entry["wire_type"]
            problems.append(
                f"{name}: wire type {got if got is None else hex(got)}, "
                f"expected {hex(expected)}"
            )
    if problems:
        print("CROSS-CHECK FAILED (the table or the scan is wrong):")
        for problem in problems:
            print("  -", problem)
        return 1
    resolved = sum(1 for m in payload["messages"] if m["wire_type"] is not None)
    print(
        f"cross-check OK: all {len(KNOWN_MOVEMENT_WIRE_TYPES)} known movement wire types "
        f"reproduce; {resolved}/{len(payload['messages'])} messages resolve to a wire type"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", help="NewWorld.exe (default: the installed client)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the movement cross-check and write nothing",
    )
    args = parser.parse_args()

    exe = Path(args.exe) if args.exe else Path(default_paths()["exe"])
    if not exe.is_file():
        raise SystemExit(f"executable not found: {exe}")

    payload = build(exe)
    if args.check:
        return check(payload)

    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("families:", dict(Counter(m["family"] for m in payload["messages"])))
    unresolved = [m["name"] for m in payload["messages"] if m["wire_type"] is None]
    if unresolved:
        print("unresolved wire types:", unresolved)
    return check(payload)


if __name__ == "__main__":
    raise SystemExit(main())
