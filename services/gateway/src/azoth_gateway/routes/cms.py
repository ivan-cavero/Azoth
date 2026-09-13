"""CMS (news / tiles). ETag is mandatory: the client crashes without it.

Bodies are preloaded from research/schemas/live at startup; requests never
touch disk. MOTD is registry-driven (registry.motd_body, hot-reloaded) and no
longer loaded here. Unknown CMS subpaths fall through to discovery (404).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..util.etag import etag_for


@dataclass(frozen=True)
class CmsDoc:
    key: str
    body: bytes
    etag: str


def is_cms_path(path: str) -> str | None:
    p = path.split("?", 1)[0]
    if "newsstories" in p and p.endswith("metadata.json"):
        return "news"
    if "marketingtiles" in p and p.endswith("metadata.json"):
        return "tiles"
    if "/motd/" in p and p.endswith(".json"):
        return "motd"
    return None


def load_cms(schemas: Path) -> dict[str, CmsDoc]:
    files = {
        "news": schemas / "cms_news.json",
        "tiles": schemas / "cms_tiles.json",
    }
    docs: dict[str, CmsDoc] = {}
    for key, fp in files.items():
        body = fp.read_bytes()
        docs[key] = CmsDoc(key=key, body=body, etag=etag_for(body))
    return docs
