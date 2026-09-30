"""ETag helpers: precompute once, compare on each request (no per-request hashing)."""

from __future__ import annotations

import hashlib


def etag_for(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def matches_if_none_match(inm: str | None, etag: str) -> bool:
    if not inm:
        return False
    inm = inm.strip()
    return inm == "*" or etag in inm
