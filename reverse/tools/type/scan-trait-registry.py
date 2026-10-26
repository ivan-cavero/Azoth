"""Regenerate research/atlas/aoi-trait-registry.json: the AOI trait message map.

WHY THIS EXISTS
===============
The server-side replication architecture is an area-of-interest TRAIT system
(`Amazon::Hub::Aoi`). Each trait registers a set of message types it handles, and
those registrations survive in the binary as mangled C++ names of the form

    ?$InstallRegistrationHook@V<Message>@<Trait>@<SubNs>@@@<Ns>@<Root>@@YA_NXZ

which is an `InstallRegistrationHook` template instantiation for one message of
one trait. Reading the trait and message out of the mangled name is
LAYOUT-INDEPENDENT: the compiler wrote both, so no adjacency guess is involved.
That makes this a stronger signal than the GUID regions, where a name and a GUID
can be merely neighbours (see `scan-az-types.py`).

WHY IT MATTERS FOR THE PRIVATE SERVER
-------------------------------------
`PhysicsTrait` alone registers ~76 message types, and they are the physics
protocol in full: `RegisterCharacterMsg` / `UnregisterCharacterMsg`,
`RequestCharacterSetPositionMsg` / `...WithOrientationMsg`,
`RequestCharacterPositionDeltaMsg` / `...WithOrientationMsg`,
`RequestCharacterResizeMsg`, `RequestIsCharacterReadyMsg`,
`RegisterRigidBodyMsg` / `UpdateRigidBodyMsg` / `UnregisterRigidBodyMsg`, the AOI
detector family (`RegisterDetectorMsg`, `MoveDetectorMsg`, `ResizeDetectorMsg`),
and the physics queries (`QueryWorldRayCastMsg`, `QueryWorldMeleeAttackMsg`).
So "give the player a body" and "move an NPC" are both expressed in this
namespace, which is why this map is the prerequisite for both open goals.

These messages carry NO GUID and are NOT Javelin typed messages: they are
dispatched inside the trait system. `Hub::Javelin::ClientMessages` (the
client-facing set) is the one to consult for what reaches the client.

Usage:
    python reverse/tools/scan-trait-registry.py [--exe PATH] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402

# The kind layout put this file one level deeper than the reorg assumed:
# `parents[2]` is `reverse/`, so every path below resolved one level too high.
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "research" / "atlas" / "aoi-trait-registry.json"

# ?$InstallRegistrationHook@V<Message>@<Trait>@<SubNs>@@@<Ns>@<Root>@@YA_NXZ
HOOK = re.compile(
    r"\?\$InstallRegistrationHook@V([A-Za-z0-9_]+)@([A-Za-z0-9_]+)@"
    r"([A-Za-z0-9_]+)@@@([A-Za-z0-9_]+)@([A-Za-z0-9_]+)@@YA_NXZ".encode()
)

# Hand-read from the mangled names and stable across the binary.
PINNED_TRAITS = {
    "Aoi::PhysicsTrait": (
        "RegisterCharacterMsg",
        "UnregisterCharacterMsg",
        "RequestCharacterSetPositionMsg",
        "RequestCharacterSetPositionWithOrientationMsg",
        "RequestCharacterPositionDeltaMsg",
        "RequestCharacterPositionDeltaWithOrientationMsg",
        "RequestIsCharacterReadyMsg",
        "RegisterRigidBodyMsg",
        "UpdateRigidBodyMsg",
        "UnregisterRigidBodyMsg",
    ),
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build(exe: Path) -> dict:
    data = exe.read_bytes()
    traits: dict[str, set[str]] = {}
    for match in HOOK.finditer(data):
        message, trait, sub_ns, ns, root = (g.decode() for g in match.groups())
        traits.setdefault(f"{sub_ns}::{trait}", set()).add(message)
    ordered = {
        name: sorted(messages) for name, messages in sorted(traits.items())
    }
    return {
        "$comment": (
            "Every AOI trait this build registers, with the message types it handles, read from "
            "the mangled '?$InstallRegistrationHook@V<Message>@<Trait>@...' template names. "
            "Layout-independent (the compiler wrote both halves), so this is [E], unlike the "
            "proximity-paired GUID regions. These messages have NO GUID and are NOT Javelin typed "
            "messages; they dispatch inside the trait system. 'Hub::Javelin::ClientMessages' is the "
            "client-facing set. Regenerate with reverse/tools/scan-trait-registry.py."
        ),
        "build_sha256": sha256_of(exe),
        "trait_count": len(ordered),
        "pair_count": sum(len(v) for v in ordered.values()),
        "traits": ordered,
    }


def check(payload: dict) -> int:
    problems = []
    for trait, messages in PINNED_TRAITS.items():
        got = set(payload["traits"].get(trait, ()))
        missing = [m for m in messages if m not in got]
        if missing:
            problems.append(f"{trait}: missing {missing}")
    if problems:
        print("PINNED-TRAIT CHECK FAILED:")
        for problem in problems:
            print("  -", problem)
        return 1
    physics = payload["traits"].get("Aoi::PhysicsTrait", [])
    print(
        f"pinned check OK: all {len(PINNED_TRAITS)} traits reproduce; "
        f"{payload['trait_count']} traits, {payload['pair_count']} trait/message pairs, "
        f"Aoi::PhysicsTrait carries {len(physics)} messages"
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
    return check(payload)


if __name__ == "__main__":
    raise SystemExit(main())
