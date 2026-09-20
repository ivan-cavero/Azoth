"""S3 remote-config mock (Azoth-local).

Real flow (official, from captures): after Omni credentials the client pulls
StackConfig layers from ags-javelin-remote-config (path-style AND
virtual-hosted URLs) for ProductId / RegionId / CognitoId / WorldId, in both
`applications/public` and `applications/publicGameplay` trees.

Shapes were never captured in the clear (TLS); sizes were. v1 serves valid
JSON padded with spaces to the captured size (length fallback, not shape
guessing): `{"azoth":true,<spaces>}`. v2 (2026-09-17): the client reads
`game-security.*` keys from the WorldId layer — without them it fails the
REP registration with `Errors::connection_server_requires_anticheat`
(Ghidra: FUN_146193620 reads the keys listed in GAME_SECURITY below).
"""

from __future__ import annotations

import json

# (key substring, size in bytes), longest-substring-first matching.
SIZES: tuple[tuple[str, int], ...] = (
    ("publicGameplay/configuration-sets/CognitoId", 5887),
    ("publicGameplay/configuration-sets/ProductId", 1856),
    ("publicGameplay/configuration-sets/RegionId", 872),
    ("publicGameplay/configuration-sets/WorldId", 146),
    ("applications/public/configuration-sets/CognitoId", 1070),
    ("applications/public/configuration-sets/RegionId", 542),
    ("applications/public/configuration-sets/ProductId", 190),
    ("applications/public/configuration-sets/WorldId", 146),
)

_STEM = b'{"azoth":true'

# game-security keys the client reads (Ghidra FUN_146193620, lea-chain from
# category string 0x1484cb2f0). Do NOT include eos-product-id / eos-client-id:
# those make ClientSDK try to init EOS, which is not present on the private
# runtime and fails as @eos_unknown_error / server_requires_anticheat
# (Game.log 2026-09-18 16:37:17, 5ms after REP socket). Official WorldId
# layer is only 146B — disable flags only.
GAME_SECURITY: dict = {
    "enable-anticheat": False,
    "enable-anticheat-kicking": False,
    "enable-heat-tracking": False,
    "eos-kick-all": False,
    "eos-enable-gm-ac": False,
}


def is_s3_path(path: str) -> bool:
    p = path.split("?", 1)[0]
    return "configuration-sets" in p


def _pad(doc: dict, size: int) -> bytes:
    raw = json.dumps(doc, separators=(",", ":")).encode()
    if len(raw) >= size:
        return raw
    # Replace the closing `}` with spaces + `}` so the document stays
    # valid JSON and matches the captured Content-Length.
    pad = size - len(raw)
    return raw[:-1] + b" " * pad + b"}"


def _game_security_doc() -> dict:
    # FUN_146193620 looks up the BARE key `enable-anticheat` on the
    # layer document (lea 0x1461936a7 -> 0x1484cb300). Nested
    # `game-security.enable-anticheat` and dotted copies are invisible
    # to that lookup → it JE-skips the store and the runtime default
    # stays true. Serve bare + nested + dotted on EVERY layer so a
    # ProductId-first merge cannot keep the default.
    doc = {"azoth": True, "game-security": GAME_SECURITY}
    for k, v in GAME_SECURITY.items():
        doc[k] = v
        doc[f"game-security.{k}"] = v
    return doc


def s3_body(path: str) -> bytes | None:
    p = path.split("?", 1)[0]
    for sub, size in SIZES:
        if sub in p:
            return _pad(_game_security_doc(), size)
    return None
