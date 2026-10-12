#!/usr/bin/env python3
"""Watch the HUD connection indicator on the left, and say what colour it is.

WHY. The red cable icon is a HUD element and the `Game.log` does NOT record it (see
the discovery note `hud_cable_icon_not_in_log`). Three separate diagnoses went wrong
by quoting log counters while the user was watching this icon. The icon sits on the
left edge, vertically centred, and looks like two unplugged cable connectors plus a
warning triangle; it goes absent -> yellow -> red as the session degrades.

It sits over grass and flowers, so a naive "find saturated red" scan finds poppies
first. This samples the indicator's own box and reports the hue mix, so the verdict
is about that box and nothing else.

Usage:
  python scripts/watch-indicator.py                 # until the client exits
  python scripts/watch-indicator.py --minutes 5
  python scripts/watch-indicator.py --save          # keep the crops as evidence
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / ".azoth" / "captures" / "azoth_shot.png"
EVIDENCE = ROOT / ".azoth" / "captures" / "indicator"

# The indicator's box in the captured client image (1382x807 for a 1366x768 client).
# Measured 2026-10-10 from a screenshot the user confirmed showed the red cable.
BOX = (34, 350, 130, 470)


def classify(im) -> tuple[str, dict]:
    """(verdict, detail) for the indicator box."""
    crop = im.crop(BOX)
    px = crop.load()
    w, h = crop.size
    red = yellow = total = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            total += 1
            # saturated red: the icon's red is a flat, bright pink-red
            if r > 130 and g < 110 and b < 130 and (r - g) > 45:
                red += 1
            # amber/yellow: r and g high, b clearly lower
            elif r > 140 and g > 110 and b < 110 and (r - b) > 50 and abs(r - g) < 70:
                yellow += 1
    red_pct = 100.0 * red / total
    yellow_pct = 100.0 * yellow / total
    if red_pct >= 0.6:
        verdict = "RED (disconnected)"
    elif yellow_pct >= 0.6:
        verdict = "YELLOW (warning)"
    else:
        verdict = "absent/other"
    return verdict, {"red_pct": round(red_pct, 2), "yellow_pct": round(yellow_pct, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=6.0)
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    from PIL import Image  # noqa: PLC0415

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    print(f"watching the HUD indicator box {BOX} every {args.interval:.0f}s\n")
    last = None
    n = 0
    while True:
        os.system(f'"{ROOT / ".azoth" / "venv" / "Scripts" / "python.exe"}" '
                  f'"{ROOT / "scripts" / "shot.py"}" >NUL 2>&1')
        if not SHOT.is_file():
            time.sleep(args.interval)
            continue
        try:
            im = Image.open(SHOT).convert("RGB")
        except OSError:
            time.sleep(args.interval)
            continue
        if im.size[0] < BOX[2] or im.size[1] < BOX[3]:
            print(f"  capture is {im.size}, smaller than the box -- wrong window?")
            time.sleep(args.interval)
            continue

        verdict, detail = classify(im)
        stamp = datetime.now(UTC).strftime("%H:%M:%SZ")
        marker = "  <-- CHANGED" if verdict != last else ""
        print(f"  {stamp}  {verdict:22} red={detail['red_pct']:>5}% "
              f"yellow={detail['yellow_pct']:>5}%{marker}", flush=True)
        if args.save and verdict != last:
            n += 1
            # verdict can be "absent/other": sanitise it, a bare split() puts a path
            # separator into the filename and the save then raises FileNotFoundError.
            slug = verdict.split()[0].replace("/", "-")
            out = EVIDENCE / f"{stamp.replace(':', '')}-{slug}-{n}.png"
            im.crop(BOX).resize(((BOX[2] - BOX[0]) * 4, (BOX[3] - BOX[1]) * 4)).save(out)
            print(f"      saved {out.name}")
        last = verdict

        if deadline and time.time() > deadline:
            break
        time.sleep(args.interval)

    print("\nnote: correlate each line with the client's state machine in Game.log at")
    print("the same UTC second -- this is the only instrument that sees the icon.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
