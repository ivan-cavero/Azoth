"""Entitlements mock.

Observed (2026-09-11 session, discovery dumps 0009/0010):
* POST /players/games/new-world/platforms/steam/entitlements/sync
* GET  /players/games/new-world/platforms/steam/entitlements
  Headers: Content-Type application/x-amz-json-1.1, X-Amz-Api-Version 2024-...

Response shape RE'd by nw-private-server/first-light (URL-first Ghidra trace:
FUN_1474caa10 builds the URL, FUN_1474c2420 parses the response):
* sync has NO JSON response parser — {} is the intended stub.
* list is a generic paginated list {hasMoreResults, lineItems[]} — NOT
  {entitlements: [...]}, that wrapper was invented. Per entry: strings
  everywhere except numeric `amount` (acquisitionPersonaId, acquisitionType,
  amount, createdDate, productId, transactionId, type).

Override: <discovery_dir>/entitlements.json (list), <discovery_dir>/entitlements_sync.json.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .omni import AZOTH_PERSONA

LIST_OVERRIDE_NAME = "entitlements.json"
SYNC_OVERRIDE_NAME = "entitlements_sync.json"


def entitlements_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / LIST_OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc = {
        "hasMoreResults": False,
        "lineItems": [
            {
                "acquisitionPersonaId": AZOTH_PERSONA,
                "acquisitionType": "Grant",
                "amount": 1,
                "createdDate": now,
                "productId": "STEAM_APP_ID.1063730",
                "transactionId": "azoth-base-game",
                "type": "BaseGame",
            },
        ],
    }
    return (json.dumps(doc) + "\n").encode()


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
