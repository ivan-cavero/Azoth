"""Report walking episodes with their direction, timing and true speed.

WHY THIS EXISTS
===============
The world log's `ts` has ONE-SECOND resolution, so a displacement divided by the timestamp
difference is meaningless inside a second: 31 samples in "1.00 s" produced a fabricated
8.5 u/s. Speed has to come from displacement per SAMPLE times the measured sample rate.

This also splits the session into episodes and reports each episode's heading against the
camera yaw, which is how the four movement keys are told apart: with the camera fixed, W, S, A
and D must produce four headings 90 degrees apart. That four-way pattern is what confirms the
frame, because a single direction cannot distinguish a 90-degree error from a sign error.

Usage:
    python scripts/measure-episodes.py .azoth/logs/world.log --from-line 1200127
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import statistics
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from logwire import decode_input, split_records  # noqa: E402


def parse_ts(value: str) -> float:
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").timestamp()


def clock(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("--from-line", type=int, default=0)
    ap.add_argument("--floor", type=float, default=0.15)
    ap.add_argument("--min-episode", type=int, default=4)
    ap.add_argument("--gap", type=float, default=0.6,
                    help="a gap in seconds that closes an episode")
    args = ap.parse_args()

    per_peer: dict[str, list[tuple]] = defaultdict(list)
    with Path(args.log).open("r", encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            if n < args.from_line:
                continue
            if '"app-data"' not in line:
                continue
            brace = line.find("{")
            if brace < 0:
                continue
            try:
                ev = json.loads(line[brace:])
            except ValueError:
                continue
            if ev.get("event") != "app-data":
                continue
            raw, ts = ev.get("raw"), ev.get("ts")
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

    for peer, samples in sorted(per_peer.items(), key=lambda kv: -len(kv[1])):
        samples.sort(key=lambda s: s[0])
        if len(samples) < 2:
            continue
        span = samples[-1][0] - samples[0][0]
        rate = (len(samples) - 1) / span if span > 0 else 0.0
        print(f"===== peer {peer}")
        print(f"   samples {len(samples)} over {span:.0f} s -> measured sample rate "
              f"{rate:.2f} Hz")

        # Group consecutive moving pairs into episodes, splitting on a time gap too:
        # two separate key presses inside the same second must not merge.
        episodes: list[list[tuple]] = []
        run: list[tuple] = []
        prev_ts = None
        for a, b in zip(samples, samples[1:]):
            dt = b[0] - a[0]
            dx, dy = b[3] - a[3], b[4] - a[4]
            dist = math.hypot(dx, dy)
            moving = dist >= args.floor
            gap = prev_ts is not None and (b[0] - prev_ts) > args.gap
            if moving and not gap:
                run.append((b[0], dx, dy, dist, b[1], b[2]))
            else:
                if len(run) >= args.min_episode:
                    episodes.append(run)
                run = [(b[0], dx, dy, dist, b[1], b[2])] if moving else []
            prev_ts = b[0]
        if len(run) >= args.min_episode:
            episodes.append(run)

        print(f"   episodes (>= {args.min_episode} moving pairs): {len(episodes)}")
        for i, ep in enumerate(episodes, 1):
            n = len(ep)
            path = sum(e[3] for e in ep)
            # True speed: n intervals at the measured rate, NOT the 1-second timestamps.
            duration = n / rate if rate > 0 else 0.0
            speed = path / duration if duration > 0 else 0.0
            yaws = [e[4] for e in ep]
            yaw_mean = math.degrees(sum(yaws) / len(yaws))
            yaw_span = math.degrees(max(yaws) - min(yaws))
            # Mean heading, from the summed vector (not the mean of angles, which
            # breaks across the +/-180 wrap).
            sx = sum(e[1] for e in ep)
            sy = sum(e[2] for e in ep)
            heading = math.degrees(math.atan2(sy, sx))
            offset = (heading - yaw_mean) % 360.0
            print(f"     ep{i:2d} {clock(ep[0][0])}-{clock(ep[-1][0])} "
                  f"{n:3d} pairs  path {path:6.2f} u  {duration:4.2f} s  "
                  f"{speed:5.2f} u/s  yaw {yaw_mean:7.2f} (span {yaw_span:5.1f})  "
                  f"heading {heading:7.2f}  offset {offset:6.1f}")

        # The four-way test: with the camera fixed, the distinct key directions show up as
        # distinct offsets. Report them clustered.
        buckets = Counter()
        for ep in episodes:
            sx = sum(e[1] for e in ep)
            sy = sum(e[2] for e in ep)
            yaw_mean = math.degrees(sum(e[4] for e in ep) / len(ep))
            offset = (math.degrees(math.atan2(sy, sx)) - yaw_mean) % 360.0
            buckets[round(offset / 10.0) * 10 % 360] += 1
        print(f"   episode offsets (10-degree buckets): {dict(sorted(buckets.items()))}")

        # Speed distribution per episode, which is what a validator threshold needs.
        speeds = []
        for ep in episodes:
            path = sum(e[3] for e in ep)
            duration = len(ep) / rate if rate > 0 else 0.0
            if duration > 0:
                speeds.append(path / duration)
        if speeds:
            speeds.sort()
            print(f"   episode speeds u/s: min {speeds[0]:.2f}  "
                  f"median {statistics.median(speeds):.2f}  max {speeds[-1]:.2f}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
