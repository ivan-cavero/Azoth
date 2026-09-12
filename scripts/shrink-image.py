"""Achica una captura antes de leerla. Uso:

    python scripts/shrink-image.py <src.png> [out.jpg] [maxPx]

Si la imagen pesa <= 100KB la deja como está y devuelve el mismo path.
Imprime el path usable por el tool `read`.
"""

import sys
from pathlib import Path

MAX_BYTES = 100 * 1024


def shrink(src: str, out: str = "", max_px: int = 768, quality: int = 55) -> Path:
    p = Path(src)
    if p.stat().st_size <= MAX_BYTES:
        return p
    from PIL import Image

    dest = Path(out) if out else p.with_suffix(".small.jpg")
    im = Image.open(src).convert("RGB")
    im.thumbnail((max_px, max_px))
    im.save(dest, "JPEG", quality=quality, optimize=True)
    return dest


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(shrink(*sys.argv[1:4]))
