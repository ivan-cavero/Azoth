"""Measure a walk from the world log: speed, the yaw frame, and the position-block shape.

WHY THIS EXISTS
===============
Two client properties cannot be read from code and could not be settled from a standing
session (scripts/measure-angle-frame.py found only 6 displacements in 195,152 samples):

  * the angle frame -- is `a` the camera yaw with forward = (-sin, cos)? A wrong sign or a
    90-degree error reports a forward walk as a sideways one, which this project has already
    done once.
  * the walk speed -- the validator's threshold. Tuned on a walk at 3.83 u/s on 1.400; if
    1.460 walks at a different speed, a ported threshold rejects legitimate movement.

Method: split the log per peer (a log can hold several clients, and pooling them produces a
fake two-state "flip" -- measured, see docs/archive/odd-tasks/remeasure-1460.md), order each peer's
samples, and only then look at displacement. Speed comes from displacement over the sample's
own timestamp, not from an assumed 20 Hz, so a stalled stream cannot inflate it.

Usage:
    python scripts/measure-walk.py .azoth/logs/world.log
    python scripts/measure-walk.py .azoth/logs/world.log --from-line 1182815
"""

from __future__ import annotations

import argparse
import datetime
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from logwire import MARKER, decode_input, iter_events, split_records  # noqa: E402


def parse_ts(value: str) -> float:
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").timestamp()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("--from-line", type=int, default=0,
                    help="skip the first N lines (a session boundary)")
    ap.add_argument("--floor", type=float, default=0.15,
                    help="displacement floor in units; below this a pair counts as still")
    ap.add_argument("--min-episode", type=int, default=4,
                    help="minimum consecutive displacements to call it an episode")
    args = ap.parse_args()

    # peer -> list of (t, yaw, pitch, x, y, body_len, marker_off)
    per_peer: dict[str, list[tuple]] = defaultdict(list)
    quad_counts: Counter = Counter()
    skipped = 0

    with Path(args.log).open("r", encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            if n < args.from_line:
                continue
            if '"app-data"' not in line:
                continue
            brace = line.find("{")
            if brace < 0:
                continue
            import json
            try:
                ev = json.loads(line[brace:])
            except ValueError:
                continue
            if ev.get("event") != "app-data":
                continue
            raw = ev.get("raw")
            ts = ev.get("ts")
            if not raw or not ts:
                continue
            try:
                datagram = bytes.fromhex(raw)
            except ValueError:
                continue
            for channel, payload in split_records(datagram):
                if channel != 1:
                    continue
                d = decode_input(payload)
                if d is None:
                    continue
                yaw, pitch, x, y, body, idx, _tgt = d
                per_peer[ev.get("peer")].append(
                    (parse_ts(ts), yaw, pitch, x, y, len(body), idx))
                # How many plausible position quads follow the marker: 1 = one position,
                # 5 = the sliding buffer measured on 1.400.
                remaining = len(body) - (idx + 4)
                plausible = 0
                for q in range(remaining // 16):
                    base = idx + 4 + q * 16
                    if base + 20 > len(body):
                        break
                    import struct
                    _, _, qx, qy = struct.unpack(">4f", body[base:base + 16])
                    if 1000.0 < qx < 20000.0 and 1000.0 < qy < 20000.0:
                        plausible += 1
                quad_counts[plausible] += 1

    if skipped:
        print(f"skipped {skipped} unparseable lines")

    print("== position-block shape (plausible quads after the marker) ==")
    for n, c in sorted(quad_counts.items()):
        print(f"   {n} quad(s): x{c}")
    print()

    for peer, samples in sorted(per_peer.items(), key=lambda kv: -len(kv[1])):
        samples.sort(key=lambda s: s[0])
        print(f"===== peer {peer}: {len(samples)} samples, "
              f"{samples[0][0]:.0f}..{samples[-1][0]:.0f} "
              f"({samples[-1][0] - samples[0][0]:.0f} s)")
        distinct = {(round(s[3], 2), round(s[4], 2)) for s in samples}
        print(f"   distinct positions (0.01 u): {len(distinct)}")
        marker_offsets = Counter(s[6] for s in samples)
        print(f"   marker body offsets: {dict(marker_offsets.most_common(5))}")

        # --- displacement census -------------------------------------------------
        disps = []
        for a, b in zip(samples, samples[1:]):
            dt = b[0] - a[0]
            dx, dy = b[3] - a[3], b[4] - a[4]
            dist = math.hypot(dx, dy)
            disps.append((dt, dx, dy, dist, b[1], b[2]))
        moving = [d for d in disps if d[3] >= args.floor]
        print(f"   pairs {len(disps)}, moving (>= {args.floor} u) {len(moving)}")
        if not moving:
            print("   no movement above the floor -- this peer stood still\n")
            continue

        # --- speed, from displacement over the sample's own timestamp ------------
        speeds = [d[3] / d[0] for d in moving if d[0] > 0.001]
        if speeds:
            speeds.sort()
            n = len(speeds)
            print(f"   instantaneous speed u/s: "
                  f"p10 {speeds[int(.1*n)]:.3f}  p50 {speeds[n//2]:.3f}  "
                  f"p90 {speeds[int(.9*n)]:.3f}  max {speeds[-1]:.3f}")

        # --- the frame test ------------------------------------------------------
        # forward = (-sin(yaw), cos(yaw))  =>  heading = yaw + 90 deg.
        deltas = Counter()
        for dt, dx, dy, dist, yaw, pitch in moving:
            heading = math.degrees(math.atan2(dy, dx))
            yaw_deg = math.degrees(yaw)
            deltas[round(((heading - yaw_deg) % 360.0) / 5.0) * 5 % 360] += 1
        total = sum(deltas.values())
        print("   (heading - yaw) mod 360, 5-degree buckets, top 6:")
        for deg, c in deltas.most_common(6):
            print(f"      {deg:5d} deg: x{c} ({100.0 * c / total:.1f}%)")
        top_deg, top_c = deltas.most_common(1)[0]
        share = 100.0 * top_c / total
        if 85 <= top_deg <= 95 and share >= 60.0:
            print(f"   FRAME CONFIRMED: forward = (-sin(yaw), cos(yaw)); "
                  f"{top_deg} deg holds for {share:.1f}% of displacements")
        elif 85 <= top_deg <= 95:
            print(f"   FRAME CONSISTENT but thin: {top_deg} deg on {share:.1f}%")
        else:
            print(f"   FRAME NOT CONFIRMED: dominant offset {top_deg} deg ({share:.1f}%)")

        # --- in-frame decomposition over the whole session ----------------------
        fwd = lat = 0.0
        for dt, dx, dy, dist, yaw, pitch in moving:
            fx, fy = -math.sin(yaw), math.cos(yaw)
            fwd += dx * fx + dy * fy
            lat += dx * (-fy) + dy * fx
        if abs(fwd) + abs(lat) > 1e-6:
            share_lat = 100.0 * abs(lat) / (abs(fwd) + abs(lat))
            print(f"   in-frame: forward {fwd:+.2f} u, lateral {lat:+.2f} u "
                  f"(lateral share {share_lat:.1f}%)")

        # --- episodes of sustained displacement ---------------------------------
        episodes = []
        run = []
        for d in disps:
            if d[3] >= args.floor:
                run.append(d)
            elif run:
                if len(run) >= args.min_episode:
                    episodes.append(run)
                run = []
        if len(run) >= args.min_episode:
            episodes.append(run)
        print(f"   sustained episodes (>= {args.min_episode} consecutive moving pairs): "
              f"{len(episodes)}")
        for i, ep in enumerate(episodes[:6], 1):
            dur = sum(d[0] for d in ep)
            dist = sum(d[3] for d in ep)
            yaws = [d[4] for d in ep]
            deltas_ep = Counter()
            for dt, dx, dy, dist_i, yaw, pitch in ep:
                heading = math.degrees(math.atan2(dy, dx))
                deltas_ep[round(((heading - math.degrees(yaw)) % 360.0) / 10.0) * 10 % 360] += 1
            top = deltas_ep.most_common(1)[0]
            print(f"     ep{i}: {len(ep)} pairs, {dur:.2f} s, {dist:.2f} u, "
                  f"mean {dist / dur if dur else 0:.3f} u/s, "
                  f"yaw {math.degrees(min(yaws)):.1f}..{math.degrees(max(yaws)):.1f} deg, "
                  f"dominant offset {top[0]} deg")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
