"""GET /prod/game/worlds/list/... = ListWorlds (the world list, shape RE'd).

RE (NewWorld.exe .rdata path table @0x84ff388):
    /prod/game/worlds/list/jwt/omni | /jwt | (bare)
These are the REST paths of the `ListWorlds` operation, whose response model is
`ListWorldsResponseBody` (keys: Worlds, RecommendedWorlds, PendingWorldMerges,
World{PublicName, PublicStatusCode, WorldName, WorldStatus, WorldType,
WorldVersion, QueueWaitTimeSec, WorldAgeDays, WorldPopulationStatus, IsFull,
IsRecommended, MaxConnectionCount, TransferToRegion}).

This is what fills the landing screen's Game.GetWorldList; the separate
`/prod/game/getlogininfo/...` (GetLoginInfo) fills Game.GetLoginInfoLists.

Body comes from the central registry (data/worlds.json).
Override: <discovery_dir>/worlds_list.json served verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

from .registry import load, worlds_list_doc

OVERRIDE_NAME = "worlds_list.json"


def worlds_list_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return (json.dumps(worlds_list_doc(load(discovery_dir))) + "\n").encode()


def is_worlds_list_path(path: str) -> bool:
    return "/game/worlds/list" in path.split("?", 1)[0]
