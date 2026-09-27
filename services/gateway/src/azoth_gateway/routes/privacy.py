"""AgsPrivacySettingsService mock (Azoth-local).

Why this exists: the client's LevelInfoChanged handler (FUN_146446800)
drops the world load with `LevelInfoChanged javContext.IsMasterPlayer is
false` unless byte [+0xa2] of the javContext is 1. The ONLY direct writer
of that byte in .text is 0x14160a754 (`mov [rax+0xa2], bl`), inside the
AgsPrivacySettingsService endpoint client (FUN_14160a1f0, key strings
`omni.privacy-settings.client-endpoint` / `AgsPrivacySettingsServiceEndpointClient`).
Until the client completes a privacy-settings round-trip for our persona,
the world never loads: no LevelInfoChanged processing, no
`clientContext->Initialize`, black screen, `connection_player_timeout`.

Wire (RE'd from NewWorld.exe strings, no live capture exists yet):
* Host: client.agsprivacysettingsservice.amazongames.com (Caddy cert +
  hosts allowlist already cover it; the gateway answers every Host).
* Path segments: /players/ + /games/ + /privacy-settings (adjacent string
  table 0x1486f4680). Required fields: PlayerId, GameAlias
  ("MISSING_PARAMETER" / "Missing required field [PlayerId|GameAlias]").
* RPC names (vtable-adjacent): GetPrivacySettingsForPlayer,
  CreateOrUpdatePrivacySettingsForPlayer
  (Javelin.RPC.StubbedAgsPrivacySettingsService/*).
* Response keys (string table): lastUpdateDate, errorCode, allowedValues,
  x-amzn-token.

Served shape: permissive superset. Unknown keys are ignored by the
client's FNV-1a runtime key hashing (only registered property hashes
match), so extra keys are free and missing keys are the risk. Region
answers us-west-2 (our cluster); every setting present allows.

Override: <discovery_dir>/privacy.json is served verbatim (no restart).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .identity import AZOTH_PERSONA

OVERRIDE_NAME = "privacy.json"

GAME_ALIAS = "new-world"


def _privacy_doc(persona_id: str = AZOTH_PERSONA) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "PlayerId": persona_id,
        "GameAlias": GAME_ALIAS,
        "lastUpdateDate": now,
        "errorCode": 0,
        "region": "us-west-2",
        "client-mode": "online",
        "settings": {
            "region": "us-west-2",
            "isMasterPlayer": True,
            "masterPlayer": True,
            "MasterPlayer": True,
            "presence": "online",
            "Presence": "online",
            "allowInvites": True,
            "canInvite": True,
            "isVisible": True,
        },
        "allowedValues": ["online", "offline", "busy"],
        "x-amzn-token": "azoth-privacy-token",
    }


def privacy_response(
    discovery_dir: Path | None = None, persona_id: str = AZOTH_PERSONA
) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return (json.dumps(_privacy_doc(persona_id)) + "\n").encode()


def is_privacy_path(path: str) -> bool:
    p = path.split("?", 1)[0].rstrip("/")
    return (
        "/privacy-settings" in p
        or "/GetPrivacySettingsForPlayer" in p
        or "/CreateOrUpdatePrivacySettingsForPlayer" in p
    )
