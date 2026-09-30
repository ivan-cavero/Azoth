"""GET /prod/game/getlogininfo/... (Azoth-local mock).

Body is generated from the world/region registry (data/worlds.json — see
registry.py): one ListWorldsResponseBody entry + LoginInfoList entry per
registered world. The 1.400 client polls this right after omni credentials
(observed: /prod/game/getlogininfo/jwt/omni, retried every 10s).

Unknowns (iterate via the override file — strict JSON parsing means a missing
key or wrong type can surface as a client-side parse error, cf. STATUS.md):
* exact key casing (queue log shows PascalCase WorldId/WorldName, so both
  casings are emitted until the live session disambiguates)
* whether the world list is embedded here or fetched from another route
* what the client actually reads from the login token claims

Override: <discovery_dir>/getlogininfo.json is served verbatim (no restart).
"""

from __future__ import annotations

import json
from pathlib import Path

from .registry import getlogininfo_doc, load

OVERRIDE_NAME = "getlogininfo.json"


def getlogininfo_response(
    discovery_dir: Path | None = None, region_id: str | None = None
) -> bytes | None:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            raw = fp.read_bytes()
            if b"__http_error" in raw:
                    return None  # 400-probe: caller answers HTTP 400
            return raw
    return (
        json.dumps(getlogininfo_doc(load(discovery_dir), region_id)) + "\n"
    ).encode()


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
