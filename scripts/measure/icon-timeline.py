#!/usr/bin/env python3
"""Sample the HUD connection indicator and write a timestamped colour timeline.

WHY. The red cable icon is a HUD element that `Game.log` does NOT record, and three
diagnoses went wrong by quoting log counters while the user watched this icon. The
icon is at the LEFT EDGE, vertically centred (about x 34-130, y 350-470 in a
1382x807 capture), and it goes absent -> yellow -> red. It renders over grass and
flowers, so a naive "find saturated red" scan finds poppies; sampling the box is what
makes the reading unambiguous.

This version captures the window in-process (no subprocess per sample) so the cadence
is tight, and it writes one CSV row per sample next to the crops. Correlate a row
with `Game.log` at the same UTC second.

Usage:
  python scripts/icon-timeline.py --minutes 12
  python scripts/icon-timeline.py --minutes 12 --crops
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import csv
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from winwindow import find_game_window  # noqa: E402

OUT_DIR = ROOT / ".azoth" / "captures" / "icon"
BOX = (34, 350, 130, 470)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def capture(hwnd: int) -> tuple[bytes, int, int] | None:
    """(BGRA top-down buffer, width, height) for the window, or None."""
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    hbmp = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0,
                                  ctypes.byref(ctypes.c_void_p()), None, 0)
    gdi32.SelectObject(hdc_mem, hbmp)
    user32.PrintWindow(hwnd, hdc_mem, 2)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    return buf.raw, w, h


def sample(buf: bytes, w: int, h: int, box: tuple[int, int, int, int]) -> dict:
    """Classify the indicator by the HUE of its saturated pixels.

    The window is captured with PrintWindow, which comes back with a strong blue
    cast over the whole scene (measured 2026-10-11: the woodwork behind the icon
    reads rgb(0,40,40) and rgb(40,80,80), i.e. blue-dominant). So neither a
    'saturated red' nor a 'saturated yellow' count identifies the icon -- the first
    versions of this file reported RED for a WHITE/cyan icon and for a BLUE one.

    What is stable is that the icon is the only strongly SATURATED thing in its box,
    and its colour decides the state:
      red-dominant  -> disconnected
      amber-dominant-> warning
      blue/white    -> connected (the HUD uses blue for the live state)
    So: find saturated pixels, then decide by channel dominance.
    """
    x0, y0, x1, y1 = box
    if x1 > w or y1 > h:
        return {"verdict": "no-window", "red": 0, "amber": 0, "blue": 0, "sat_pct": 0.0}
    red = amber = blue = sat = 0
    for y in range(y0, y1):
        base = y * w * 4
        for x in range(x0, x1):
            o = base + x * 4
            b, g, r = buf[o], buf[o + 1], buf[o + 2]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx - mn <= 50 or mx <= 90:
                continue  # background, not the icon
            sat += 1
            if r >= g and r >= b and (r - b) > 40 and (r - g) > 30:
                red += 1
            elif r > b and g > b and (r - b) > 40:
                amber += 1
            elif b >= r and b >= g:
                blue += 1
    total = (x1 - x0) * (y1 - y0)
    if red >= 0.6 * sat and red > 0:
        verdict = "DISCONNECTED(red)"
    elif amber >= 0.6 * sat and amber > 0:
        verdict = "WARNING(amber)"
    elif blue >= 0.5 * sat and blue > 0:
        verdict = "CONNECTED(blue)"
    elif sat == 0:
        verdict = "absent"
    else:
        verdict = "other"
    return {
        "verdict": verdict,
        "red": red,
        "amber": amber,
        "blue": blue,
        "sat_pct": round(100.0 * sat / total, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=12.0)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--crops", action="store_true")
    ap.add_argument("--wait", type=float, default=300.0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"timeline-{datetime.now(UTC).strftime('%H%M%S')}.csv"
    fh = csv_path.open("w", newline="", encoding="utf-8")
    writer = csv.writer(fh)
    writer.writerow(["utc", "verdict", "red", "amber", "blue", "sat_pct"])

    print(f"waiting up to {args.wait:.0f}s for the game window (box {BOX})", flush=True)
    hwnd = None
    deadline = time.time() + args.wait
    while time.time() < deadline:
        hwnd = find_game_window()
        if hwnd:
            break
        time.sleep(2)
    if not hwnd:
        print("no NewWorld.exe window appeared")
        return 1
    print(f"watching hwnd={hwnd:#x} -> {csv_path.name}", flush=True)

    from PIL import Image  # noqa: PLC0415

    end = time.time() + args.minutes * 60
    last = None
    while time.time() < end:
        got = capture(hwnd)
        if got is None:
            time.sleep(args.interval)
            continue
        buf, w, h = got
        r = sample(buf, w, h, BOX)
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        writer.writerow([stamp, r["verdict"], r["red"], r["amber"], r["blue"],
                         r["sat_pct"]])
        fh.flush()
        mark = "  <== CHANGE" if r["verdict"] != last else ""
        print(f"  {stamp}Z  {r['verdict']:18} red={r['red']:>6} amber={r['amber']:>6} "
              f"blue={r['blue']:>6} sat={r['sat_pct']:>5}%{mark}", flush=True)
        if args.crops and r["verdict"] != last:
            x0, y0, x1, y1 = BOX
            img = Image.frombytes("RGBA", (w, h), buf).convert("RGB")
            crop = img.crop(BOX)
            crop = crop.resize(((x1 - x0) * 5, (y1 - y0) * 5))
            p = OUT_DIR / f"{stamp.replace(':', '')}-{r['verdict']}.png"
            crop.save(p)
            print(f"      saved {p.name}")
        last = r["verdict"]
        time.sleep(args.interval)

    fh.close()
    print(f"\ntimeline: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
