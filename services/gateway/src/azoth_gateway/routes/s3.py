"""S3 remote-config mock (Azoth-local).

Real flow (official, from captures): after Omni credentials the client pulls
StackConfig layers from ags-javelin-remote-config (path-style AND
virtual-hosted URLs) for ProductId / RegionId / CognitoId / WorldId, in both
`applications/public` and `applications/publicGameplay` trees.

Shapes were never captured in the clear (TLS); sizes were. v1 serves valid
JSON padded with spaces to the captured size (length fallback, not shape
guessing): `{"azoth":true,<spaces>}`. If the client rejects it, the dumps
show us the next signal.
"""

from __future__ import annotations

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


def is_s3_path(path: str) -> bool:
    p = path.split("?", 1)[0]
    return "configuration-sets" in p


def s3_body(path: str) -> bytes | None:
    p = path.split("?", 1)[0]
    for sub, size in SIZES:
        if sub in p:
            pad = size - len(_STEM) - 1
            if pad < 0:
                return _STEM + b"}"
            return _STEM + b" " * pad + b"}"
    return None
