#!/usr/bin/env python3
"""Watch one private session from BOTH sides, live, on one clock.

WHY. Diagnosing the ~40 s post-spawn disconnect went wrong repeatedly because the
two logs were read at different times, in different units, with different greps:

* `OnLocalNetworkConnectionWarning` is NOT the red cable; counting it said nothing
  about the connection the user was looking at.
* `Game.log` timestamps are UTC; `.azoth/logs/world.log` JSON `ts` is UTC; local wall
  clock is +02:00. Comparing them by eye produced two wrong conclusions.
* `services/world/rep_traffic.jsonl` (what `log_event` writes) and
  `.azoth/logs/world.log` (the child's stdout, which `az.py` captures) are DIFFERENT
  files. Reading only the second one once made it look like the server had been
  silent for 40 minutes when in fact the file had simply stopped being written.
* Measuring 2 minutes after entering the world misses a disconnect at ~44 s and
  reports a healthy session that is already dead.

So: one process, one clock, both sides, sampled continuously, with the client's own
state machine as the spine.

Usage:
  python scripts/watch-session.py                    # watch until the client exits
  python scripts/watch-session.py --interval 5
  python scripts/watch-session.py --minutes 10
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "AGS" / "New World" / "Game.log"
WORLD_LOG = ROOT / ".azoth" / "logs" / "world.log"
TRAFFIC = ROOT / "services" / "world" / "rep_traffic.jsonl"

# Client-side lines that matter, in the order they occur in a healthy session.
CLIENT_MARKERS = (
    "start REP connection",
    "received registration response",
    "LevelInfoChanged",
    "Calling clientContext->Initialize",
    "[ClientContext] Initialize()",
    "[ClientContext] Cleanup()",
    "player spawn succeeds",
    "Update state",
    "disconnected from REP",
    "OnDisconnection",
    "ActorContainerConnect",
    "transportError",
    "clientContext == nullptr",
    "is timeout",
    "OnLocalNetworkConnectionWarning",
)

SERVER_MARKERS = (
    "listening-dtls",
    "dtls-established",
    "v3-registered",
    "replay-armed",
    "replay-complete-quiet",
    "activity-stream-armed",
    "dtls-session-reset",
)

SERVER_COUNTED = (
    "replay-chunk",
    "heartbeat",
    "input-response",
    "keepalive",
    "resend",
    "activity-stream",
    "app-data",
    "outbound-app-data",
)


def game_line(line: str) -> tuple[str, str] | None:
    """(utc_time, text) for a Game.log line, or None."""
    if not line.startswith("<"):
        return None
    end = line.find(">")
    if end < 0:
        return None
    stamp = line[1:end].split(".")[0]
    return stamp, line[end + 1:].strip()


def read_traffic(limit_bytes: int = 4_000_000) -> list[dict]:
    """The tail of the traffic jsonl, parsed. It is append-only and can be huge."""
    if not TRAFFIC.is_file():
        return []
    size = TRAFFIC.stat().st_size
    with TRAFFIC.open("rb") as fh:
        if size > limit_bytes:
            fh.seek(size - limit_bytes)
            fh.readline()  # drop the partial line
        raw = fh.read().decode("utf-8", errors="replace")
    out = []
    for line in raw.splitlines():
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def game_running() -> bool:
    """True while a NewWorld.exe process exists. tasklist prints 'INFO: No tasks...'
    when there is none, so match the image name, not the word NewWorld."""
    out = os.popen('tasklist /FI "IMAGENAME eq NewWorld.exe" /NH').read()
    return "NewWorld.exe" in out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--minutes", type=float, default=0, help="0 = until the client exits")
    args = ap.parse_args()

    if not GAME_LOG.is_file():
        print(f"no Game.log at {GAME_LOG}")
        return 1

    print(f"watching\n  client {GAME_LOG}\n  server {WORLD_LOG}\n  traffic {TRAFFIC}\n")

    seen_client = 0
    seen_server_marks: set[str] = set()
    counts: dict[str, int] = {}
    spawn_utc: str | None = None
    first = True
    deadline = time.time() + args.minutes * 60 if args.minutes else None

    while True:
        # ---- client side -------------------------------------------------
        lines = GAME_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[seen_client:]:
            parsed = game_line(line)
            if parsed is None:
                continue
            stamp, text = parsed
            if not any(m in text for m in CLIENT_MARKERS):
                continue
            if "player spawn succeeds" in text:
                spawn_utc = stamp
            flag = ""
            if "clientContext == nullptr" in text or "is timeout" in text or "transportError" in text:
                flag = "  <-- PROBLEM"
            print(f"  [client {stamp}] {text[:110]}{flag}", flush=True)
        seen_client = len(lines)

        # ---- server side -------------------------------------------------
        for entry in read_traffic():
            ts = entry.get("ts", "")
            kind = entry.get("event")
            if kind in SERVER_MARKERS:
                key = f"{kind}"
                if kind in ("listening-dtls", "dtls-established", "v3-registered",
                            "dtls-session-reset"):
                    key = f"{kind}@{ts}"
                if key not in seen_server_marks:
                    seen_server_marks.add(key)
                    print(f"  [server {ts}] {kind} "
                          f"{ {k: v for k, v in entry.items() if k not in ('ts', 'event')} }"
                          [:130], flush=True)
            elif kind in SERVER_COUNTED:
                counts[kind] = counts.get(kind, 0) + 1

        if not first:
            stamp = datetime.now(UTC).strftime("%H:%M:%SZ")
            summary = " ".join(f"{k}={counts.get(k, 0)}" for k in SERVER_COUNTED
                               if counts.get(k))
            print(f"  .. {stamp} server totals: {summary or '(nothing)'}", flush=True)
        first = False

        # Stop when the client is gone (the interesting window is closed).
        if deadline is None:
            if seen_client and not game_running():
                print("\n  client process gone -- stopping")
                break
        elif time.time() > deadline:
            print("\n  time budget reached -- stopping")
            break
        time.sleep(args.interval)

    print(f"\nspawn was at {spawn_utc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
