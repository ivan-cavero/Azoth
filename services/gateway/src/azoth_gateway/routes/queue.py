"""POST/GET /prod/game/login/queue/v2/... (Azoth-local mock).

Ticket envelope RE'd by nw-private-server/first-light (Codex/Ghidra trace
2026-04-19): the parser reads the top-level "LoginQueueResponse" key and then
PascalCase fields inside — the old flat {ticket, worldId, ...} object is
ignored ("No login ticket received"). Signature is the queue handoff gate
(FUN_14643d110 -> FUN_14114b200 compares the transformed token's leading
string field, which comes from Signature): an empty string never triggers the
next-stage handoff, so it must be non-empty. QueueName maps through the
client's @mm_loginservices_location_ table; the AWS region token parses.

RepAddress points at the Javelin REP server (not built yet; see services/world).
Override: <discovery_dir>/queue.json is served verbatim (no restart).
"""

from __future__ import annotations

import json
import time
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
    ticket_id = str(uuid.uuid4())
    now = int(time.time())
    return (
        json.dumps(
            {
                "LoginQueueResponse": {
                    "AccountAge": 0,
                    "AccountIsLocked": False,
                    "CharacterId": PLACEHOLDER_CHARACTER_ID,
                    "ClientCapabilities": "",
                    "GenerateTime": now,
                    "HostHash": "",
                    "IsPermanentAppOwner": True,
                    "IsTrialOwner": False,
                    "IssueTime": now,
                    "Location": "",
                    "LocationGroupId": "",
                    "LocationId": "",
                    "PersonaId": "",
                    "RepAddress": rep,
                    "Signature": f"sig:{ticket_id}",
                    "SteamAppId": 1063730,
                    "SteamUserId": "",
                    "TicketId": ticket_id,
                    "TokenVersion": 10,
                    "WorldId": world_id,
                    "WorldName": world_name,
                }
            }
        )
        + "\n"
    ).encode()


def is_queue_path(path: str) -> bool:
    return "/prod/game/login/queue/v2" in path.split("?", 1)[0]
