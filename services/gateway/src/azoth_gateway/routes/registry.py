"""Central world/region registry: data/worlds.json is the single source of truth.

Drives getlogininfo, motd, queue and the channel region names. Ops flow
(open world / maintenance mode) edits that one JSON file; no gateway restart:
callers re-run load() per request, which only stats the active file and
re-parses when the mtime changed (same cheap pattern as the overrides).

Override: <discovery_dir>/worlds.json takes precedence over the packaged file.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .omni import _jwt

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_PATH = DATA_DIR / "worlds.json"
OVERRIDE_NAME = "worlds.json"

AZOTH_WORLD_ID = "00000000-0000-4000-8000-000000000001"
AZOTH_WORLD_NAME = "dev"

# MOTD locale keys, exact shape RE'd from research/schemas/live/cms_motd.json
# (8 locales x {announcement, warning} per world, same for global title/description).
LOCALES = ("es-ES", "es-MX", "fr-FR", "de-DE", "pl-PL", "it-IT", "pt-BR")


@dataclass(frozen=True)
class Registry:
    regions: list[dict]
    worlds: list[dict]
    mtime: int
    path: Path


_cache: tuple[int, Path, Registry] | None = None  # (mtime_ns, path, parsed)


def load(discovery_dir: Path | None) -> Registry:
    """Parsed registry; re-read only when the active file's mtime changed.

    Thread safety: worst case two threads parse concurrently and one result is
    discarded — the tuple assignment is atomic, readers never see a torn doc.
    """
    global _cache
    fp = DEFAULT_PATH
    if discovery_dir is not None:
        override = discovery_dir / OVERRIDE_NAME
        if override.is_file():
            fp = override
    mtime = fp.stat().st_mtime_ns
    if _cache is not None and _cache[0] == mtime and _cache[1] == fp:
        return _cache[2]
    try:
        doc = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Half-written/invalid file mid-edit: keep serving the last good registry
        # (hot-reload must never 500 a login); first-load failure still raises.
        if _cache is not None:
            return _cache[2]
        raise
    reg = Registry(doc.get("regions", []), doc.get("worlds", []), mtime, fp)
    _cache = (mtime, fp, reg)
    return reg


def active_world(reg: Registry, world_name: str | None = None) -> dict | None:
    for w in reg.worlds:
        if (world_name is None or w.get("name") == world_name) and w.get("status") == "ACTIVE":
            return w
    return None


def queue_fields(reg: Registry, world_name: str | None = None) -> tuple[str, str, str]:
    """(repAddress, worldId, worldName) for the queue ticket.

    First ACTIVE world (optionally by name); falls back to the first world so a
    MAINTENANCE-only registry still yields a ticket the client can parse.
    """
    w = active_world(reg, world_name) or active_world(reg)
    if w is None:
        w = reg.worlds[0] if reg.worlds else {}
    return (
        os.environ.get("AZOTH_REP_ADDRESS") or w.get("repAddress", "127.0.0.1:9000"),
        w.get("id", AZOTH_WORLD_ID),
        w.get("name", AZOTH_WORLD_NAME),
    )


def _wire_world_type(raw: str) -> str:
    """worldtype_mapper (0x1417c40a0): 'FTUE'->0, 'OpenWorld'->1, else Unknown.

    eWorldType_* are reflection labels next to the mapper, not strncmp tokens.
    """
    t = raw or "OpenWorld"
    t = t.removeprefix("eWorldType_")
    return t if t in ("OpenWorld", "FTUE") else "OpenWorld"


def _world_metadata(w: dict) -> dict:
    """WorldMetadata as registered at 0x144f54cda. `type` is an enum whose
    members are eWorldType_*; extra keys can fail a strict deserialize and
    drop the whole object (empty vector → login_no_worlds / 0x11).
    """
    maintenance = w.get("status") == "MAINTENANCE"
    short = _wire_world_type(str(w.get("type", "OpenWorld")))
    return {
        "worldId": w.get("id", AZOTH_WORLD_ID),
        "name": w.get("name", AZOTH_WORLD_NAME),
        "type": short,
        "status": w.get("status", "ACTIVE"),
        "version": w.get("version", "1.0.0"),
        # RE: usable-check FUN_1464460d0 rejects (psc & 0xffffe8b7) != 0 -> psc=1 never lists.
        "publicStatusCode": 0,
        "publicName": w.get("displayName", ""),
        "maxAccountCharacters": 4,
        "worldSet": w.get("worldSet", ""),
        "worldMetrics": {
            "worldAgeDays": 1,
            "queueSize": 0,
            "queueWaitTimeSec": 0,
            "worldPopulationStatus": "LOW",
        },
        "transferToRegion": "",
        "isFull": False,
        "isRecommended": not maintenance,
        "regionId": w.get(
            "regionId", w.get("id", "azoth-1")
        ),  # ponytail: sin esto el mundo no se asigna a la región (dropdown 0/0)
    }


def _aws_world(w: dict) -> dict:
    """ListWorlds/GetLoginInfo AWS member names (PascalCase). WorldType uses
    the mapper tokens OpenWorld/FTUE (0x1417c40a0), not eWorldType_*.
    """
    maintenance = w.get("status") == "MAINTENANCE"
    short = _wire_world_type(str(w.get("type", "OpenWorld")))
    return {
        "WorldName": w.get("name", AZOTH_WORLD_NAME),
        "PublicName": w.get("displayName", ""),
        "WorldStatus": w.get("status", "ACTIVE"),
        "WorldType": short,
        "WorldVersion": w.get("version", "1.0.0"),
        "PublicStatusCode": 1,
        "QueueWaitTimeSec": 0,
        "WorldAgeDays": 1,
        "WorldPopulationStatus": "LOW",
        "IsFull": False,
        "IsRecommended": not maintenance,
        "MaxConnectionCount": w.get("maxPlayers", 2500),
        "TransferToRegion": "",
    }


def _world_entry(w: dict) -> dict:
    # Union for tests/queue that still read WorldName on getlogininfo.
    return {
        **_world_metadata(w),
        **_aws_world(w),
    }


def worlds_list_doc(reg: Registry) -> dict:
    """GET /prod/game/worlds/list/... = ListWorlds.

    Landing screen GetWorldList; GetLoginInfoLists is filled by getlogininfo.
    Live wire is the WorldsInfo reflection model (camelCase): `worlds` /
    `recommendedWorlds` with WorldMetadata entries (see symbols.json
    worldmetadata_property_table). The PascalCase aws-sdk member names are
    dead in 1.400 (0 xrefs, decorative table 0x148702000).
    """
    entries = [_world_entry(w) for w in reg.worlds]
    # ponytail: top-level dual casing, strict per-world shape stays in _world_entry
    return {
        "worlds": entries,
        "recommendedWorlds": [],
        "Worlds": entries,
        "RecommendedWorlds": [],
    }


def getlogininfo_doc(reg: Registry) -> dict:
    login_infos = []
    for w in reg.worlds:
        now_ms = time.time_ns() // 1_000_000
        login_infos.append(
            {
                # ponytail: solo camelCase; la unión Pascal rompe el parser estricto (dropdown 0/4 -> 0/0)
                **_world_metadata(w),
                "characters": [],  # ponytail: RE GetLoginInfoLists = descriptor + characters[]; sin esto el parser estricto puede soltar la entrada
                "RepAddress": w.get("repAddress", ""),
                "JwtClaims": _jwt(
                    {"sub": w.get("id", AZOTH_WORLD_ID), "iat": now_ms, "exp": now_ms + 7_200_000}
                ),
                "GenerateTime": now_ms // 1000,
                "IssueTime": now_ms // 1000,
                "TokenVersion": 1,
            }
        )
    # GetLoginInfoResult (HTTP) is NOT ListWorlds. Putting a `Worlds` array
    # here can fail the aws-sdk-cpp unmarshaller → outcome never completes
    # (UI spinner) and ListWorlds is never requested. Worlds live on
    # GET /game/worlds/list only.
    return {
        "LoginInfoList": login_infos,
        "RecommendedWorlds": [],
        "PendingWorldMerges": [],
        "AccountIsLocked": False,
        "AllowQueueTransfer": False,
        "QueueName": "",
    }


def motd_doc(reg: Registry) -> dict:
    worlds = {}
    world_sets: dict[str, dict] = {}
    for w in reg.worlds:
        announcement = w.get("announcement", "") if w.get("status") == "MAINTENANCE" else ""
        doc = {"announcement": announcement}
        doc.update({f"{loc}-announcement": "" for loc in LOCALES})
        doc["warning"] = ""
        doc.update({f"{loc}-warning": "" for loc in LOCALES})
        worlds[w.get("id", AZOTH_WORLD_ID)] = doc
        world_sets[w.get("worldSet", "")] = {"setName": w.get("displayName", "")}
    region_announcement = next(
        (r.get("announcement", "") for r in reg.regions if r.get("status") == "ACTIVE"), ""
    )
    global_announcement = {"title": region_announcement}
    global_announcement.update({f"{loc}-title": "" for loc in LOCALES})
    global_announcement["description"] = ""
    global_announcement.update({f"{loc}-description": "" for loc in LOCALES})
    return {
        "worlds": worlds,
        "worldSets": world_sets,
        "globalAnnouncement": global_announcement,
    }


def motd_body(discovery_dir: Path | None) -> bytes:
    return (json.dumps(motd_doc(load(discovery_dir))) + "\n").encode()
