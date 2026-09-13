"""Capture the game window and emit OCR-friendly crops (upscaled, high contrast).

Usage: python scripts/ocr-window.py [title-substring] [out-dir]
Prints one path per band; run each through scripts/ocr-image.ps1.
"""

import sys
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module

capture = import_module("capture-window")

BANDS = 4


def main() -> None:
    title = sys.argv[1] if len(sys.argv) > 1 else "New World"
    out_dir = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path.home() / "AppData/Local/Temp/azoth-ocr"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    wins = capture.find_windows(title)
    if not wins:
        print(f"no window matching {title!r}", file=sys.stderr)
        sys.exit(2)
    hwnd, name = wins[0]
    img = capture.ImageGrab.grab(bbox=capture.client_rect(hwnd), all_screens=True)
    print(f"{name!r} {img.size}", file=sys.stderr)

    def prep(im: Image.Image, path: Path) -> None:
        big = im.resize(
            (im.width * 2, im.height * 2), Image.Resampling.LANCZOS
        ).convert("L")
        ImageOps.autocontrast(big, cutoff=1).save(path)

    prep(img, out_dir / "full.png")
    print(out_dir / "full.png")
    step = img.height // BANDS
    for i in range(BANDS):
        band = img.crop((0, i * step, img.width, min(img.height, (i + 1) * step + 40)))
        prep(band, out_dir / f"band{i}.png")
        print(out_dir / f"band{i}.png")


if __name__ == "__main__":
    main()
