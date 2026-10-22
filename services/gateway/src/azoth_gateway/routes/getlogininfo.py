"""GET /prod/game/getlogininfo/... for the private client.

The body comes from the region/world registry. The client consumes two
distinct models from the same response: lowercase ``worlds`` for the dropdown
and the PascalCase ``LoginInfoList`` object for the character gate. Both are
required by the 1.400 contract; see ``registry.getlogininfo_doc``.

An ignored local ``getlogininfo.json`` override remains available to the shape
harness. It changes only the response body and adds no alternate server mode.
"""

from __future__ import annotations

import json
from pathlib import Path

from .registry import getlogininfo_doc, load

OVERRIDE_NAME = "getlogininfo.json"


def getlogininfo_response(
    discovery_dir: Path | None = None,
    region_id: str | None = None,
    instance: str | None = None,
) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    body = getlogininfo_doc(load(discovery_dir), region_id, instance)
    return (json.dumps(body) + "\n").encode()


def is_getlogininfo_path(path: str) -> bool:
    return "/prod/game/getlogininfo" in path.split("?", 1)[0]


# gateway-CF CloudFront host -> registry region id (mirrors the channel JSON:
# each region's JavelinGatewayService-CF endpoint). The client talks to the
# gateway of ITS region, so the Host it connected through IS the region scope.
CF_HOST_TO_REGION = {
    "d1w0bfy6smo4d1.cloudfront.net": "fra-prod",
    "d1cjlmzk0xrm0z.cloudfront.net": "gru-prod",
    "d2oeuvxi3kfsrw.cloudfront.net": "iad-prod",
    "d3bj4csovi1fe8.cloudfront.net": "pdx-prod",
    "de4mfzk9wkelz.cloudfront.net": "syd-prod",
}


def region_from_headers(headers) -> str | None:
    """Region id from the gateway-CF host the client used (X-Forwarded-Host
    set by Caddy; falls back to Host)."""
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(":")[0]
    return CF_HOST_TO_REGION.get(host.lower())


def is_platform_user_code_path(path: str) -> bool:
    return "/auth/platform/user/code" in path.split("?", 1)[0]
