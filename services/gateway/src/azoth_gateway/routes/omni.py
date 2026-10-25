"""Omni token exchange (Azoth-local mock, RE-derived).

Shape was reverse-engineered from the OmniSDK 1.6.7 parser embedded in
NewWorld.exe (ags_fed_acc_token.cpp / ags_persona_account.cpp /
platform_persona_account.cpp). Key discovery (2026-09-09):

* Any malformed field => SDK result 203 (= 0xcb parse-error), NOT a semantic
  code. That is why every hand-guessed shape 203'd for weeks.
* The SDK reads, in order: region, limitedUseToken, platformAccount,
  account, isNewAccount, conflictingAccount, accessToken, expiresIn,
  fallbackToken.
* platformAccount => PlatformPersonaAccount { ageGroup:int, identityType:str,
  platform:str?, identityId:str, personaId:str }.
* account => AgsPersonaAccount { type:"shadow"|"full", ageGroup:int,
  identityId:str, personaId:str }. Missing account => 307.
* Session persona = account.personaId. The type is behaviour, not a label: the
  client's GetIsShadowAccount gate (landingscreenv2.luac::TryShowAGIDLink)
  shows the Amazon account-link modal only for "shadow". We serve "full" so a
  private client never lands in the linking flow.
* Tokens are JWT-looking strings (jwt_reader requires 2 dots); alg "none"
  with empty signature parses fine locally.
* iat/exp in the JWT payload are MILLISECONDS ("AGS Auth token iat %lldms").

With this exact shape the client logged: CreateSession result 0 +
persona id OK + account type Shadow (2026-09-09 18:29).
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from .identity import AZOTH_PERSONA, AZOTH_STEAM_ID  # re-exported for callers

# Rapid-iteration override: if <discovery_dir>/tokens.json exists, serve its
# bytes verbatim (no gateway restart needed between game retries). The dir is
# gitignored, so experiments never dirty the repo.
OVERRIDE_NAME = "tokens.json"


def _b64u(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _jwt(claims: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}
    return ".".join(
        (
            _b64u(json.dumps(header, separators=(",", ":")).encode()),
            _b64u(json.dumps(claims, separators=(",", ":")).encode()),
            "",  # alg "none": empty signature, jwt_reader only needs 2 dots
        )
    )


def _token_set() -> dict:
    try:
        now_ms = int(time.time() * 1000)
    except (OSError, OverflowError):  # defensive; time.time() never raises
        now_ms = 0
    access = _jwt(
        {
            "sub": AZOTH_PERSONA,
            "iss": "https://tokenservice.amazongames.com",
            "aud": "new-world",
            "iat": now_ms,
            "exp": now_ms + 7_200_000,
        }
    )
    fallback = _jwt(
        {
            "sub": AZOTH_PERSONA,
            "refresh": True,
            "iat": now_ms,
            "exp": now_ms + 86_400_000,
        }
    )
    return {
        "accessToken": access,
        "expiresIn": 7200,
        "fallbackToken": fallback,
        "limitedUseToken": "",
        "isNewAccount": False,
        "region": "us-east-1",
        "platformAccount": {
            "ageGroup": 1,
            "identityType": "steam",
            "platform": "steam",
            "identityId": AZOTH_STEAM_ID,
            "personaId": AZOTH_PERSONA,
        },
        "account": {
            "type": "full",
            "ageGroup": 1,
            "identityId": AZOTH_PERSONA,
            "personaId": AZOTH_PERSONA,
        },
    }


def tokens_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return (json.dumps(_token_set()) + "\n").encode()


def is_tokens_path(path: str) -> bool:
    return path.split("?", 1)[0].rstrip("/").endswith("/games/new-world/tokens")
