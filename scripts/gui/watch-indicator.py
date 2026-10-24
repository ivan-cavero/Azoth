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

ROOT = Path(__file__).resolve().parents[2]
SHOT = ROOT / ".azoth" / "captures" / "azoth_shot.png"
EVIDENCE = ROOT / ".azoth" / "captures" / "indicator"

# The indicator's box in the captured client image (1382x807 for a 1366x768 client).
# Measured 2026-10-10 from a screenshot the user confirmed showed the red cable.
#
# TWO INSTRUMENT BUGS FIXED 2026-10-12, both of which made this script's verdict wrong
# without saying so:
#  1. STALE CAPTURE. The loop shelled out to shot.py and then classified SHOT without ever
#     checking the file had been REWRITTEN. When shot.py failed, the previous file stayed and
#     its contents were classified. Measured: a run reported `absent/other` for all ten
#     samples while a fresh capture of the same session showed the icon plainly RED, because
#     it was reading a file written 40 minutes earlier.
#  2. WRONG SIZE. The box is in pixels for a 1382x807 capture, but the guard only rejected
#     images SMALLER than the box, so a 1920x1080 capture passed and the box then sampled a
#     different part of the screen.
# The capture must now be newer than the moment it was requested, and the box is scaled to
# the actual capture size.
BOX = (34, 350, 130, 470)
BOX_REFERENCE_SIZE = (1382, 807)


def scale_box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The indicator box in pixels for a capture of ``size``.

    The box was measured on a 1382x807 capture, so it is treated as a fraction of that and
    mapped onto whatever the capture actually is.
    """
    sx = size[0] / BOX_REFERENCE_SIZE[0]
    sy = size[1] / BOX_REFERENCE_SIZE[1]
    return (int(BOX[0] * sx), int(BOX[1] * sy), int(BOX[2] * sx), int(BOX[3] * sy))


def classify(im, box: tuple[int, int, int, int] | None = None) -> tuple[str, dict]:
    """(verdict, detail) for the indicator box."""
    box = box or scale_box(im.size)
    crop = im.crop(box)
    px = crop.load()
    w, h = crop.size
    red = yellow = total = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            total += 1
            # CALIBRATED 2026-10-13 on two measured samples, one of each kind:
            #   the real icon's red is a BRIGHT PINK: (225,109,102) and (188,82,73) - r >= 188,
            #     r-g >= 106, and g and b nearly equal (109 vs 102);
            #   a RED CURTAIN behind an NPC (the false positive that made a fixed cable read
            #     "RED 1.8%") is a DULL red: (132,65,37) - r <= 132, and b far below g.
            # So `r >= 180` alone separates them, and requiring g near b keeps browns out.
            # LIMIT: calibrated on ONE real icon sample. The dark-frame test (the icon sits on a
            # near-black plaque) does NOT work - measured dark% 46.0 for the real icon vs 47.2
            # for the curtain. Treat this verdict as a screen and check the crop.
            if r >= 180 and g >= 80 and (r - g) >= 90 and abs(g - b) <= 40:
                red += 1
            # amber/yellow. MEASURED 2026-10-13: the loose version of this rule
            # (r>140, g>110, b<110, r-b>50) matched the GOLD WALL of Aeternum's
            # buildings and reported "YELLOW 11.5%" for a crop that contains no icon at
            # all - which is how a fixed cable was nearly reported as still warning. The
            # rule now demands a much brighter, more saturated pixel than any wall sample
            # measured (wall gold peaked at (182,141,68)).
            # CAVEAT: unlike the red rule, this one is NOT validated against a real amber
            # sample - no amber capture exists. Treat a YELLOW verdict as "look at the
            # crop", never as a measurement.
            elif r >= 200 and g >= 140 and b <= 110 and (r - b) >= 100:
                yellow += 1
    red_pct = 100.0 * red / total
    yellow_pct = 100.0 * yellow / total
    # Thresholds measured 2026-10-13 against five known crops:
    #   real red icon  -> red 1.44 %, yellow 0.08 %
    #   red curtain    -> red 0.00 %, yellow 0.62 %   (false positive of the amber rule)
    #   three clean    -> red 0.00 %, yellow 0.00 / 0.00 / 0.31 %
    # So 0.6 % separates red cleanly, and amber needs to sit above 0.62 % to stop the
    # curtain tripping it. AMBER IS NOT VALIDATED: no capture of a real amber cable exists,
    # so that branch is a guess informed by the observation that amber is between clear and
    # red. A YELLOW verdict must be confirmed on the crop before it is believed.
    if red_pct >= 0.6:
        verdict = "RED (disconnected)"
    elif yellow_pct >= 2.0:
        verdict = "YELLOW (warning, UNVALIDATED rule - check the crop)"
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
        requested_at = time.time()
        os.system(f'"{ROOT / ".azoth" / "venv" / "Scripts" / "python.exe"}" '
                  f'"{ROOT / "scripts" / "shot.py"}" >NUL 2>&1')
        if not SHOT.is_file():
            print(f"  {datetime.now(UTC).strftime('%H:%M:%SZ')}  no capture written "
                  "(shot.py failed)", flush=True)
            time.sleep(args.interval)
            continue
        # Only a capture written AFTER we asked for it describes this moment; otherwise we are
        # about to classify the previous frame and present it as the current verdict.
        if SHOT.stat().st_mtime < requested_at - 1.0:
            print(f"  {datetime.now(UTC).strftime('%H:%M:%SZ')}  capture is STALE "
                  f"({int(time.time() - SHOT.stat().st_mtime)}s old: shot.py failed) "
                  "-- skipping this sample", flush=True)
            time.sleep(args.interval)
            continue
        try:
            im = Image.open(SHOT).convert("RGB")
        except OSError:
            time.sleep(args.interval)
            continue
        box = scale_box(im.size)
        if im.size[0] < box[2] or im.size[1] < box[3]:
            print(f"  capture is {im.size}, smaller than the box -- wrong window?")
            time.sleep(args.interval)
            continue

        verdict, detail = classify(im, box)
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
            im.crop(box).resize(((box[2] - box[0]) * 4, (box[3] - box[1]) * 4)).save(out)
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
