"""Entitlements mock (Azoth-local, shape GUESSED).

Observed (2026-09-11 session, discovery dumps 0009/0010):
* POST /players/games/new-world/platforms/steam/entitlements/sync
* GET  /players/games/new-world/platforms/steam/entitlements
  Headers: Content-Type application/x-amz-json-1.1, X-Amz-Api-Version 2024-...

Shadow accounts (account.type "shadow", see omni.py) are believed to skip the
full entitlements path, so an empty set should be acceptable. Guesses to
iterate via override files — strict JSON parsing, cf. STATUS.md 203 lesson.

Override: <discovery_dir>/entitlements.json (list), <discovery_dir>/entitlements_sync.json.
"""

from __future__ import annotations

import json
from pathlib import Path

LIST_OVERRIDE_NAME = "entitlements.json"
SYNC_OVERRIDE_NAME = "entitlements_sync.json"


def entitlements_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / LIST_OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return (json.dumps({"entitlements": []}) + "\n").encode()


def entitlements_sync_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / SYNC_OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return (json.dumps({}) + "\n").encode()


def is_entitlements_sync_path(path: str) -> bool:
    return "/entitlements/sync" in path.split("?", 1)[0]


def is_entitlements_path(path: str) -> bool:
    p = path.split("?", 1)[0]
    return "/entitlements" in p
