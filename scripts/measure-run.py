#!/usr/bin/env python3
"""Summarise one private-run A/B: client warnings vs the server's replay window.

WHY. `OnLocalNetworkConnectionWarning` climbing right after the spawn is the
symptom under study, and comparing two runs by eye went wrong once already (the
first A/B compared 121 warnings against a run that never entered the world). So the
comparison is mechanical: same markers, same clock, one JSON line per run.

The question it answers: are the warnings confined to the window in which the
replay is still streaming, or do they persist after the replay drains? The
WARNINGS_IN_REPLAY / WARNINGS_AFTER_REPLAY split is the whole point, because the
heartbeat, input-response and activity-stream emitters all start with the replay.

Usage:
  python scripts/measure-run.py --label A-off
  python scripts/measure-run.py --label B-on --compare A-off B-on
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "AGS" / "New World" / "Game.log"
WORLD_LOG = ROOT / ".azoth" / "logs" / "world.log"
REPORT = ROOT / ".azoth" / "logs" / "ab-runs.jsonl"

TS = re.compile(r"^<(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})")
WARN = re.compile(r"OnLocalNetworkConnectionWarning countReceived: (\d+)")


def parse_ts(text: str) -> float | None:
    """Local wall-clock seconds since midnight; the game log is local time."""
    m = TS.match(text)
    if not m:
        return None
    dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def client_events() -> dict:
    if not GAME_LOG.is_file():
        return {"error": f"missing {GAME_LOG}"}
    spawn = first = last = None
    counts: list[tuple[float, int]] = []
    markers: dict[str, int] = {}
    for line in GAME_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if "player spawn succeeds" in line and spawn is None:
            spawn = parse_ts(line)
        if "OnLocalNetworkConnectionWarning" in line:
            m = WARN.search(line)
            t = parse_ts(line)
            if m and t is not None:
                counts.append((t, int(m.group(1))))
        for marker in (
            "transportError",
            "disconnected from REP",
            "State(InGame) is timeout",
            "Initialize()",
            "Cleanup()",
        ):
            if marker in line:
                markers[marker] = markers.get(marker, 0) + 1
    if counts:
        first, last = counts[0][0], counts[-1][0]
    return {
        "log": str(GAME_LOG),
        "spawn_s": spawn,
        "first_warning_s": first,
        "last_warning_s": last,
        "warning_count": counts[-1][1] if counts else 0,
        "warning_samples": len(counts),
        "markers": markers,
        "game_log_mtime": GAME_LOG.stat().st_mtime,
    }


def server_events() -> dict:
    """Replay window and emitter counts for the CURRENT session.

    "Current" = after the last `listening-dtls`, because the world log accumulates
    sessions and filtering by timestamp by eye is the trap the handoff warns about.
    """
    if not WORLD_LOG.is_file():
        return {"error": f"missing {WORLD_LOG}"}
    lines = WORLD_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [i for i, l in enumerate(lines) if "listening-dtls" in l]
    if not starts:
        return {"error": "no listening-dtls in the world log"}
    session = []
    for line in lines[starts[-1]:]:
        t = line.strip()
        if t.startswith("[rep] "):
            t = t[6:]
        if not t.startswith("{"):
            continue
        try:
            session.append(json.loads(t))
        except json.JSONDecodeError:
            continue
    kinds: dict[str, list[str]] = {}
    for e in session:
        if "event" in e and "ts" in e:
            kinds.setdefault(e["event"], []).append(e["ts"])

    def window(kind: str) -> tuple[str, str] | None:
        ts = kinds.get(kind)
        return (ts[0], ts[-1]) if ts else None

    def epoch(ts: str) -> float:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=None
        ).timestamp()

    replay = window("replay-chunk")
    drained = (kinds.get("replay-complete-quiet") or [None])[-1]
    out = {
        "config": session[0].get("event") if session else None,
        "replay_chunks": len(kinds.get("replay-chunk", [])),
        "replay_window": replay,
        "replay_complete_quiet": drained,
        "counts": {k: len(v) for k, v in sorted(kinds.items())},
        "heartbeat_before_drain": 0,
        "activity_stream_before_drain": 0,
    }
    if drained:
        d = epoch(drained)
        out["heartbeat_before_drain"] = sum(1 for ts in kinds.get("heartbeat", []) if epoch(ts) < d)
        out["activity_stream_before_drain"] = sum(
            1 for ts in kinds.get("activity-stream", []) if epoch(ts) < d
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="name for this run, e.g. A-off")
    ap.add_argument("--compare", nargs="*", default=None,
                    help="labels to print side by side from the report file")
    args = ap.parse_args()

    run = {"label": args.label, "client": client_events(), "server": server_events()}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(run) + "\n")

    c, s = run["client"], run["server"]
    if "error" in c or "error" in s:
        print(json.dumps(run, indent=1))
        return 1

    print(f"=== {args.label} ===")
    print(f"  replay window          {s['replay_window'][0]} .. {s['replay_window'][1]}"
          f"  ({s['replay_chunks']} chunks)")
    print(f"  replay drained         {s['replay_complete_quiet']}")
    print(f"  heartbeat before drain {s['heartbeat_before_drain']}")
    print(f"  activity-stream before drain {s['activity_stream_before_drain']}")
    print(f"  warnings               {c['warning_count']}"
          f"  ({c['first_warning_s']} -> {c['last_warning_s']})")
    print(f"  markers                {c['markers']}")

    if args.compare:
        print("\n  comparison:")
        rows = []
        for line in REPORT.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("label") in args.compare:
                rows.append(r)
        for r in rows:
            cc, ss = r["client"], r["server"]
            print(
                f"    {r['label']:>8}  warnings={cc['warning_count']:>4}"
                f"  hb_before_drain={ss.get('heartbeat_before_drain', '?'):>4}"
                f"  act_before_drain={ss.get('activity_stream_before_drain', '?'):>4}"
                f"  transportError={cc['markers'].get('transportError', 0)}"
                f"  disconnected={cc['markers'].get('disconnected from REP', 0)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
