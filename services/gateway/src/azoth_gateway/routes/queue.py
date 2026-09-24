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
import re
import time
import uuid
from pathlib import Path

from .identity import (
    AZOTH_CHARACTER_ID,
    AZOTH_PERSONA,
    AZOTH_STEAM_APP_ID,
    AZOTH_STEAM_ID,
)
from .registry import load, queue_fields

OVERRIDE_NAME = "queue.json"
# Refresh path carries the issued ticket: /prod/game/login/queue/v2/<id>/jwt/omni
_REFRESH_RE = re.compile(r"/queue/v2/[^/]+/jwt")


def _ticket(rep: str, world_id: str, world_name: str) -> dict:
    """The login-ticket envelope (parser: FUN_1474e4f20 family)."""
    ticket_id = str(uuid.uuid4())
    now = int(time.time())
    return {
        "AccountAge": 0,
        "AccountIsLocked": False,
        "CharacterId": AZOTH_CHARACTER_ID,
        "ClientCapabilities": "",
        "GenerateTime": now,
        "HostHash": "",
        "IsPermanentAppOwner": True,
        "IsTrialOwner": False,
        "IssueTime": now,
        "Location": "",
        "LocationGroupId": "",
        "LocationId": "",
        "PersonaId": AZOTH_PERSONA,
        "RepAddress": rep,
        "Signature": f"sig:{ticket_id}",  # handoff gate: must be non-empty
        "SteamAppId": AZOTH_STEAM_APP_ID,
        "SteamUserId": AZOTH_STEAM_ID,
        "TicketId": ticket_id,
        "TokenVersion": 10,
        "WorldId": world_id,
        "WorldName": world_name,
    }


def queue_response(discovery_dir: Path | None = None, path: str = "") -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    rep, world_id, world_name = queue_fields(load(discovery_dir))

    if _REFRESH_RE.search(path):
        # Refresh path (GET /queue/v2/<ticketId>/jwt/omni): the ready
        # envelope. Position 0 + a full Token is what moves the client from
        # WaitingForQueuedLogin to StartREPConnection.
        ticket = _ticket(rep, world_id, world_name)
        return (
            json.dumps(
                {
                    "LoginQueueResponse": {
                        "AllowQueueTransfer": False,
                        "EstimatedTime": 0,
                        "Position": 0,
                        "QueueName": "eu-central-1",
                        "RecommendedTransferWorldId": "",
                        "RefreshInterval": 15,
                        "TicketId": ticket["TicketId"],
                        "Token": ticket,
                    }
                }
            )
            + "\n"
        ).encode()

    # Initial enqueue: issue a parseable ticket immediately (no real queue).
    return (json.dumps({"LoginQueueResponse": _ticket(rep, world_id, world_name)}) + "\n").encode()


def is_queue_path(path: str) -> bool:
    return "/prod/game/login/queue/v2" in path.split("?", 1)[0]
