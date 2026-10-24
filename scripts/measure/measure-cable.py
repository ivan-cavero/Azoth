"""Measure the HUD connection indicator, correctly, in one command.

WHY THIS EXISTS
===============
Three separate mistakes were made measuring this icon on 2026-10-13 alone, and each produced a
confident wrong answer:

1. **Classifying the whole desktop.** The indicator box in `watch-indicator.py` is in the GAME
   CLIENT's own pixel space (1366x768 here), but a desktop capture also contains the T3 window.
   Applying the box to the desktop samples a different part of the screen and reports
   `absent/other` on a session whose icon is plainly red.
2. **Classifying a stale capture.** A capture taken before the current frame is not this moment.
   `watch-indicator.py` now rejects those, and this tool takes its own capture every time.
3. **Trusting the label.** The amber rule matched Aeternum's gold walls; a crop containing no icon
   at all was reported as "YELLOW 11.5%". The rule is tightened, but the lesson stands: a verdict
   is only trustworthy with the crop saved next to it.

So this tool always (a) locates the game window, (b) captures the screen, (c) crops to the window's
CLIENT rect, (d) classifies that crop with the documented box, and (e) saves the crop so the label
can be checked by eye. It prints the crop path.

Usage:
  python scripts/measure-cable.py                 # one measurement
  python scripts/measure-cable.py --minutes 30 --interval 60   # sample a soak
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import importlib.util
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".azoth" / "captures" / "cable"


def _load_classifier():
    spec = importlib.util.spec_from_file_location(
        "watch_indicator", ROOT / "scripts" / "watch-indicator.py"
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:  # the module only defines things; this is belt and braces
        pass
    return module


def capture_client() -> tuple[object, tuple[int, int, int, int]]:
    """A PIL image of the game window's CLIENT area, plus its client rect."""
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = user32.FindWindowW(None, "New World")
    if not hwnd:
        raise SystemExit("no 'New World' window found")
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))

    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, screen_w, screen_h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, screen_w, screen_h, hdc, 0, 0, 0x00CC0020)

    class BIH(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    bi = BIH()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth = screen_w
    bi.biHeight = -screen_h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(screen_w * screen_h * 4)
    gdi32.GetDIBits(mem, bmp, 0, screen_h, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGBA", (screen_w, screen_h), bytes(buf), "raw", "BGRA", 0, 1)
    img = img.convert("RGB")
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)

    rect_tuple = (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)
    return img.crop(rect_tuple), rect_tuple


def measure(save: bool = True) -> tuple[str, dict, Path | None]:
    module = _load_classifier()
    client, rect = capture_client()
    verdict, detail = module.classify(client, module.BOX)
    path = None
    if save:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        slug = verdict.split()[0].replace("/", "-")
        path = EVIDENCE / f"{stamp}-{slug}.png"
        box = module.BOX
        client.crop(box).resize(
            ((box[2] - box[0]) * 4, (box[3] - box[1]) * 4)
        ).save(path)
    return verdict, {"rect": rect, "size": client.size, **detail}, path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--minutes", type=float, default=0, help="0 = a single measurement")
    args = ap.parse_args()

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    print(f"{'when':22} {'verdict':22} {'red%':>6} {'yellow%':>8}  crop")
    while True:
        try:
            verdict, detail, path = measure()
        except SystemExit as exc:
            print(f"{datetime.now(UTC).strftime('%H:%M:%SZ'):22} {exc}")
            return 1
        print(
            f"{datetime.now(UTC).strftime('%H:%M:%SZ'):22} {verdict:22} "
            f"{detail['red_pct']:>6} {detail['yellow_pct']:>8}  "
            f"{path.name if path else '-'}",
            flush=True,
        )
        if deadline is None or time.time() > deadline:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
