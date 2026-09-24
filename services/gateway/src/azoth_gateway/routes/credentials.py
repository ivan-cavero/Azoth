"""Credentials Omni mock (Azoth-local, RE-derived from the client parser).

The game-side credentials parser (NewWorld.exe, OmniAuthBackend /
AuthStackCredentialsProvider) reads camelCase keys via a JSON member lookup
that CRASHES (access-violation reading the parsed double) when a field is
missing:

    accessKeyId   (string, ASIA…)
    secretAccessKey (string)
    sessionToken  (string)
    expiration    (double — unix seconds as NUMBER, not ISO string!)
    region        (string)

The old STS-shaped response (AccessKeyId/SecretKey/Expiration ISO-string)
made the member lookup return NULL and NewWorld.exe crashed at
+0x7465476 (cvttsd2si of a null deref) right after
"Calling Http API: …/prod/credentials/omni".
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .identity import AZOTH_PERSONA  # re-exported for existing callers


def _alnum(nchars: int) -> str:
    # Strict [A-Za-z0-9] (no +/=): some clients validate key charset.
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    out: list[str] = []
    while len(out) < nchars:
        for byte in os.urandom(16):
            if len(out) >= nchars:
                break
            out.append(alphabet[byte % len(alphabet)])
    return "".join(out)


def _override_persona(discovery_dir: Path | None) -> str | None:
    if discovery_dir is None:
        return None
    try:
        doc = json.loads((discovery_dir / "tokens.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    account = doc.get("account")
    if isinstance(account, dict):
        val = account.get("personaId") or account.get("identityId")
        if isinstance(val, str) and val.startswith("amzn1."):
            return val
    for key in ("personaId", "id"):
        val = doc.get(key)
        if isinstance(val, str) and val.startswith("amzn1."):
            return val
    return None


def credentials_response(discovery_dir: Path | None = None, persona: str | None = None) -> bytes:
    persona = persona or _override_persona(discovery_dir) or AZOTH_PERSONA
    try:
        exp_epoch = int(time.time()) + 55 * 60  # NUMBER, not ISO string
    except (OSError, OverflowError):  # defensive; time.time() never raises
        exp_epoch = 0
    akid = "ASIA" + _alnum(16)
    secret = _alnum(40)
    token = _alnum(128)
    doc = {
        # Exact keys the client parser reads (camelCase, crash if missing).
        "accessKeyId": akid,
        "secretAccessKey": secret,
        "sessionToken": token,
        "expiration": exp_epoch,
        "region": "us-east-1",
        # Flat legacy copies kept for other consumers/tools.
        "AccessKeyId": akid,
        "SecretKey": secret,
        "SecretAccessKey": secret,
        "SessionToken": token,
        "Expiration": exp_epoch,
        "type": "Full",
        "accountType": "Full",
        "ownership": "permanent",
        "personaId": persona,
    }
    return (json.dumps(doc) + "\n").encode()


def is_credentials_path(path: str) -> bool:
    return path.split("?", 1)[0].rstrip("/").endswith("/prod/credentials/omni")
