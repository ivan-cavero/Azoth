"""Render a screenshot as ASCII so a text-only agent can read the layout.

OCR gives loose words; this gives the shape (where the rows, columns and boxes
are), which is what you need before clicking anything.

Usage: python scripts/ascii-view.py <image.png> [width] [cropTop] [cropBottom]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps

RAMP = " .:-=+*#%@"


def render(
    path: Path, width: int = 110, top: int = 0, bottom: int | None = None
) -> str:
    img = Image.open(path).convert("L")
    if top or bottom:
        img = img.crop((0, top, img.width, bottom or img.height))
    # terminal cells are about twice as tall as they are wide
    height = max(8, img.height * width // (2 * img.width))
    small = ImageOps.autocontrast(img.resize((width, height), Image.Resampling.BOX))
    data = small.tobytes()
    levels = len(RAMP) - 1
    lines = []
    for y in range(height):
        base = y * width
        lines.append(
            "".join(RAMP[data[base + x] * levels // 256] for x in range(width))
        )
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: ascii-view.py <image.png> [width] [cropTop] [cropBottom]"
        )
    try:
        width = int(sys.argv[2]) if len(sys.argv) > 2 else 110
        top = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        bottom = int(sys.argv[4]) if len(sys.argv) > 4 else None
    except ValueError as exc:
        raise SystemExit(f"width/crop values must be integers: {exc}") from exc
    path = Path(sys.argv[1])
    try:
        size = Image.open(path).size
    except OSError as exc:
        raise SystemExit(f"cannot open {path}: {exc}") from exc
    print(
        f"# {path.name} {size} crop_y={top}..{bottom or size[1]} rendered {width} cols"
    )
    print(render(path, width, top, bottom))


if __name__ == "__main__":
    main()
