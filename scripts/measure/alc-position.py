#!/usr/bin/env python3
"""Read the player's position out of the client's channel-1 stream, and report the evidence.

WHY. The server's authority over movement starts with reading the claim the client already
sends ~20x/s. `azoth_world.javelin.alc` does the decoding; this tool is what proves the
decoding on real traffic instead of on three hand-picked fixtures, and it prints the three
numbers the desync design depends on:

  * **how many records carry a position**, and how many do not (the pre-load bodies);
  * **when each session became readable** — the real load signal, measured at t+8..14 s
    after the first channel-1 record rather than at a 60 s timer;
  * **the reference offset** between the wire claim and the client's own accessor, when
    `--probes` points at a Frida capture directory. That offset is an instrument property
    (2.04-4.03 u, per session), NOT a desync, and this is the only place it belongs.

Usage:
  python scripts/alc-position.py                                  # default dump
  python scripts/alc-position.py --dump services/world/rep_traffic.jsonl
  python scripts/alc-position.py --probes .azoth/captures/probes   # adds the offset
  python scripts/alc-position.py --sessions                        # load timing per session
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "world" / "src"))

from azoth_world.javelin import parse_datagram, parse_envelope  # noqa: E402
from azoth_world.javelin import alc  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402
from azoth_world.movement import ReferenceOffset  # noqa: E402

DEFAULT_DUMP = ROOT / "services" / "world" / "rep_traffic.jsonl"


def _iso_to_epoch(text: str) -> float:
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc
    ).timestamp()


def channel_one_payloads(path: Path, limit: int | None = None):
    """Yield ``(epoch, payload)`` for every channel-1 record in a traffic log."""
    seen: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"channel": 1' not in line:
                continue
            line = line.strip()
            if line.startswith("[rep] "):
                line = line[6:]
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") != "app-data":
                continue
            raw = event.get("raw_full") or event.get("raw")
            if not raw or raw in seen:
                continue
            seen.add(raw)
            try:
                envelope, body = parse_envelope(bytes.fromhex(raw))
                if envelope.is_compressed:
                    body = decompress_lz4_block(body)
                datagram = parse_datagram(body)
            except Exception:  # noqa: BLE001 - a malformed datagram is not this tool's job
                continue
            try:
                when = _iso_to_epoch(event["ts"])
            except (KeyError, ValueError):
                continue
            for record in datagram.messages:
                if record.channel == 1:
                    yield when, record.payload
            if limit is not None and seen.__len__() >= limit:
                return


def load_probes(directory: Path) -> list[tuple[float, float, float, str]]:
    """``(epoch, x, y, source)`` from the client's own position accessor.

    ``source`` is the probe file, which is also the session key: one probe run is one
    client session, and the reference offset is per session.
    """
    samples: list[tuple[float, float, float, str]] = []
    for path in sorted(directory.glob("player-position-*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not row.get("ok"):
                    continue
                values = row.get("vals") or []
                if len(values) < 2:
                    continue
                samples.append((row["t"], values[0]["f"], values[1]["f"], path.name))
    samples.sort()
    return samples


def report(dump: Path, probes: Path | None, show_sessions: bool) -> int:
    with_position = 0
    without = 0
    ambiguous = 0
    positions: collections.Counter[tuple[float, float]] = collections.Counter()
    timeline: list[tuple[float, bool]] = []
    marker_offsets: collections.Counter[int] = collections.Counter()

    for when, payload in channel_one_payloads(dump):
        claim = alc.read_claim(payload)
        timeline.append((when, claim is not None))
        if claim is None:
            without += 1
            try:
                _target, _type_id, body = alc.split_container(payload)
            except alc.AlcError:
                continue
            if body.count(alc.POSITION_MARKER) > 1:
                ambiguous += 1
            continue
        with_position += 1
        marker_offsets[claim.marker_offset] += 1
        positions[(round(claim.x, 3), round(claim.y, 3))] += 1

    total = with_position + without
    print(f"channel-1 records: {total}")
    print(f"  with a position : {with_position}"
          f"  ({100.0 * with_position / total:.1f}%)" if total else "")
    print(f"  without one     : {without}  (pre-load bodies)")
    print(f"  ambiguous (>1 marker): {ambiguous}")
    print()
    if marker_offsets:
        print("position block offset in the body (top 6):")
        for offset, count in marker_offsets.most_common(6):
            print(f"  {offset:4d}  x{count}")
        print("  -> the block MOVES; locating it by the 0.05 marker is required")
        print()
    print(f"distinct positions: {len(positions)}")
    for (x, y), count in positions.most_common(8):
        print(f"  ({x:10.3f}, {y:10.3f})  x{count}")

    if show_sessions:
        print()
        print("load timing per session (gap > 120 s starts a new one):")
        starts = [0]
        for i in range(1, len(timeline)):
            if timeline[i][0] - timeline[i - 1][0] > 120:
                starts.append(i)
        for start in starts:
            segment = timeline[start:start + 400]
            t0 = segment[0][0]
            first = next((i for i, (_, ready) in enumerate(segment) if ready), None)
            stamp = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc)
            if first is None:
                print(f"  {stamp:%Y-%m-%d %H:%M:%SZ}  NEVER ready in 400 records")
            else:
                print(f"  {stamp:%Y-%m-%d %H:%M:%SZ}  ready at t+{segment[first][0] - t0:.0f}s")

    if probes is not None:
        print()
        samples = load_probes(probes)
        if not samples:
            print(f"no probe samples under {probes}")
            return 0
        # Pair each probe sample with the nearest channel-1 claim in time, and only keep
        # pairs where the client stood still, so a moving player's prediction lead is not
        # mistaken for the instrument offset. Calibrated PER SESSION: pooling sessions is
        # exactly what makes the offset look incoherent.
        by_time: list[tuple[float, tuple[float, float]]] = []
        for when, payload in channel_one_payloads(dump):
            claim = alc.read_claim(payload)
            if claim is not None:
                by_time.append((when, (claim.x, claim.y)))
        by_time.sort()
        times = [t for t, _ in by_time]
        import bisect

        per_session: dict[str, ReferenceOffset] = {}
        for i in range(len(samples) - 1):
            t, x, y, source = samples[i]
            t_next, x_next, y_next, _ = samples[i + 1]
            if (x, y) != (x_next, y_next) or t_next - t > 0.6:
                continue
            j = bisect.bisect_left(times, t)
            candidates = [k for k in (j - 1, j) if 0 <= k < len(by_time)]
            if not candidates:
                continue
            k = min(candidates, key=lambda k: abs(by_time[k][0] - t))
            if abs(by_time[k][0] - t) > 1.5:
                continue
            per_session.setdefault(source, ReferenceOffset()).observe(by_time[k][1], (x, y))

        print("reference offset per session (wire claim vs the client's own accessor):")
        print(f"  {'session':40s} {'n':>5s}  {'offset':>18s}  {'|d|':>6s}  {'residual':>8s}")
        any_calibration = False
        for source, reference in sorted(per_session.items()):
            calibration = reference.calibrate()
            if calibration is None:
                continue
            any_calibration = True
            print(f"  {source:40s} {calibration.samples:5d}  "
                  f"({calibration.dx:+7.3f},{calibration.dy:+7.3f})  "
                  f"{calibration.magnitude:6.3f}  {calibration.residual:8.4f}")
        if not any_calibration:
            print("  no paired samples (probe and dump do not overlap in time)")
        else:
            print("  -> per-session, and the magnitude varies: an INSTRUMENT offset, not a")
            print("     desync. A low residual means the reader is trustworthy for that")
            print("     session; DesyncTracker never uses this, because it compares the")
            print("     claim against the SERVER's own position, which needs no offset.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", default=str(DEFAULT_DUMP))
    parser.add_argument("--probes", default=None,
                        help="directory of player-position-*.jsonl probe captures")
    parser.add_argument("--sessions", action="store_true", help="report load timing")
    args = parser.parse_args()

    dump = Path(args.dump)
    if not dump.is_file():
        print(f"no such traffic log: {dump}")
        return 2
    probes = Path(args.probes) if args.probes else None
    return report(dump, probes, args.sessions)


if __name__ == "__main__":
    raise SystemExit(main())
