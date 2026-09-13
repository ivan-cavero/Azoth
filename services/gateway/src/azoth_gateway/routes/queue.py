"""POST/GET /prod/game/login/queue/v2/... (Azoth-local mock, log-derived).

Fields the live client consumed (client_expect.json, Game.log — the JSON body
itself was TLS):
    ticket "<worldId>_<uuid>", location "" (open world; empty skips FTUE),
    RepAddress "ip:port", WorldId <uuid>, WorldName <str>, CharacterId <uuid>.

World fields come from the registry (data/worlds.json, first ACTIVE world);
AZOTH_REP_ADDRESS env var still overrides RepAddress. Unknowns: exact casing
of ticket/location (lowercase in the log) and whether the client expects
queue-position polling responses before the final ticket.

Override: <discovery_dir>/queue.json is served verbatim (no restart).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .characters import PLACEHOLDER_CHARACTER_ID
from .registry import load, queue_fields

OVERRIDE_NAME = "queue.json"


def queue_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    rep, world_id, world_name = queue_fields(load(discovery_dir))
    return (
        json.dumps(
            {
                "ticket": f"{world_id}_{uuid.uuid4()}",
                "location": "",
                "RepAddress": rep,
                "WorldId": world_id,
                "WorldName": world_name,
                "CharacterId": PLACEHOLDER_CHARACTER_ID,
            }
        )
        + "\n"
    ).encode()


def is_queue_path(path: str) -> bool:
    return "/prod/game/login/queue/v2" in path.split("?", 1)[0]
