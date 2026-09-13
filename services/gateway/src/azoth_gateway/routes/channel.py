"""Channel config: answers ANY .../STEAM_APP_ID.*.json path.

The 1.400 client builds garbage channel URLs (STEAM_APP_ID.1.BRANCH.<rand>.json);
the URL does not come from Steam interfaces, so the fix is at network level:
match by substring, always serve channel-azoth.json (single cluster azoth-1).

Region displayName/localizedName are overridden from the registry
(data/worlds.json) after load, so the region dropdown shows the registry
names. Re-rendered only when the channel file or registry mtime changes.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from ..util.etag import etag_for
from .registry import Registry, load

CHANNEL_PATH = Path(__file__).resolve().parent.parent / "data" / "channel-azoth.json"

# Base is packaged with the gateway: preload once (dev edits restart the
# gateway). Only the registry region-name override is hot-reloaded.
try:
    _BASE: dict = json.loads(CHANNEL_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError) as e:
    raise RuntimeError(f"channel base file unreadable: {CHANNEL_PATH} ({e})") from e

_cache: tuple[int, tuple[bytes, str]] | None = None  # (registry mtime, out)


def channel_response(discovery_dir: Path | None) -> tuple[bytes, str]:
    global _cache
    reg: Registry = load(discovery_dir)
    if _cache is not None and _cache[0] == reg.mtime:
        return _cache[1]
    doc = deepcopy(_BASE)
    for r in reg.regions:
        region = doc.get(r.get("id"))
        if region is not None:
            region["displayName"] = r.get("displayName", "")
            region["localizedName"] = r.get("displayName", "")
    body = (json.dumps(doc, indent=2) + "\n").encode()
    out = (body, etag_for(body))
    _cache = (reg.mtime, out)
    return out


def is_channel_path(path: str) -> bool:
    p = path.split("?", 1)[0]
    if not p.endswith(".json"):
        return False
    base = p.rsplit("/", 1)[-1]
    # Basename match only: CMS paths also contain STEAM_APP_ID but live under
    # /newsstories/, /marketingtiles/ and /motd/ (checked first by the router).
    return base.startswith("STEAM_APP_ID")
