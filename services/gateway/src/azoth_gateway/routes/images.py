"""Content-service images mock (Azoth-local placeholder).

Observed (2026-09-11 session, discovery dumps 0012-0026): the client fetches
.dds images from client.content-service.amazongames.com:
* nw_maintenance__modal_ct-*.dds / nw_maintenance_tile*.dds (maintenance modal)
* newstile2.dds (news tiles)

A 404 makes the client retry 5x and show blank/white art (observed live).
This serves a valid 256x256 uncompressed BGRA DDS placeholder (dark navy,
built once at import with struct.pack) so the UI renders something and stops
retrying. Real art can replace the placeholder file later.

Override: <discovery_dir>/placeholder.dds served verbatim.
"""

from __future__ import annotations

import struct
from pathlib import Path

OVERRIDE_NAME = "placeholder.dds"

_W = _H = 256
# DDS_HEADER: magic, size 124, CAPS|HEIGHT|WIDTH|PITCH|PIXELFORMAT, dims, pitch,
# 11 reserved, DDS_PIXELFORMAT (RGB 32bpp BGRA masks), DDSCAPS_TEXTURE.
# Total header slot is 128 bytes: 4 magic + 124 struct + 4 unused.
_HEADER = (
    struct.pack(
        "<4s7I11I8I4I",
        b"DDS ",
        124,
        0x0000100F,
        _H,
        _W,
        _W * 4,
        0,
        0,
        *([0] * 11),
        32,
        0x40,  # DDPF_RGB
        0,
        32,
        0x00FF0000,
        0x0000FF00,
        0x000000FF,
        0xFF000000,
        0x1000,
        0,
        0,
        0,
    )
    + b"\x00" * 4  # header slot is 128 bytes: magic(4) + struct(124) + 4 unused
)
_DDS = _HEADER + b"\x30\x10\x08\xff" * (_W * _H)  # BGRA dark navy


def images_response(discovery_dir: Path | None = None) -> bytes:
    if discovery_dir is not None:
        fp = discovery_dir / OVERRIDE_NAME
        if fp.is_file():
            return fp.read_bytes()
    return _DDS


def is_images_path(path: str) -> bool:
    p = path.split("?", 1)[0]
    return "/images/" in p
