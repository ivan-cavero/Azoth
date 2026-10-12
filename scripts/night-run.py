#!/usr/bin/env python3
"""One unattended A/B run: stack env is already set, launch, probe, and report.

Why this exists. Every live experiment needs the same shape: start the position
probe BEFORE the client enters the world (the entity is only observable during the
world load), drive `private-run.py`, then collect the three independent signals
that must agree before a claim is made:

  * the server log (what we sent: `position-reply`, `start-movement`, resends);
  * `Game.log` (client-side unmarshal/validation errors, the timeout lines);
  * the Frida probe counters (did the client's own reader actually run?);
  * a screenshot for the HUD icon, which no log records.

The repo rule this encodes: "the parse consumes the body exactly" is necessary but
not sufficient, and "no error in the log" is not evidence that a message was used.
The probe counters are the discriminator.

Usage:
  python scripts/night-run.py --tag ch0-rel --probe frida-position-consumer --minutes 22
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".azoth" / "venv" / "Scripts" / "python.exe"
LOGS = ROOT / ".azoth" / "logs"
RUNS = ROOT / ".azoth" / "night" / "runs"
GAME_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "AGS" / "New World" / "Game.log"


def count_events(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not path.is_file():
        return counts
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("[rep] "):
                line = line[6:]
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line).get("event")
            except ValueError:
                continue
            if ev:
                counts[ev] = counts.get(ev, 0) + 1
    return counts


def game_log_markers() -> dict[str, int]:
    """Count markers in the CURRENT Game.log.

    The client ROTATES Game.log on every launch (the previous file moves to
    LogBackups), so a byte offset taken before the launch is meaningless after it.
    Counting the whole current file is correct, provided the caller reads it after
    the client has started.
    """
    try:
        text = GAME_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    markers = (
        "player spawn succeeds",
        "Failed to unmarshal",
        "unmarshalError",
        "ValidationError",
        "transportError",
        "OnLocalNetworkConnectionWarning",
        "State(InGame) is timeout",
        "ActorContainerDisconnect",
        "exiting to main menu",
        "Cleanup()",
    )
    return {m: text.count(m) for m in markers}


def wait_for_gateway(seconds: float = 120.0) -> bool:
    """Wait until Caddy can serve the CMS manifest from the gateway.

    WHY THIS EXISTS. `python az.py dev` returns as soon as it has SPAWNED the three
    services; the gateway takes another ~20-30 s to bind 127.0.0.1:8080. Launching
    the client inside that window makes Caddy answer 502 for
    `d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json`, and the client then
    stalls at the frontend with

        Unable to call JavelinGame::RequestHandleLoginSteps - Auth manager does not exist

    which looks like an auth bug and is actually a startup race. Measured
    2026-10-11 07:28:48 (caddy.log: status 502, "dial tcp 127.0.0.1:8080 ...
    actively refused"). This helper makes the race impossible to hit again.
    """
    import urllib.error
    import urllib.request

    url = "https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json"
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
                last = resp.status
                if resp.status == 200:
                    print(f"[night] gateway healthy (HTTP {resp.status})")
                    return True
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
        time.sleep(5)
    print(f"[night] gateway did NOT become healthy: {last}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--probe", default="frida-position-consumer")
    ap.add_argument("--minutes", type=float, default=22.0)
    ap.add_argument("--settle", type=float, default=45.0)
    ap.add_argument("--no-launch", action="store_true")
    args = ap.parse_args()

    if not wait_for_gateway():
        print("[night] refusing to launch: the gateway is not serving the CMS manifest")
        return 2

    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%H%M%S")
    base = RUNS / f"{args.tag}-{stamp}"
    base.mkdir(parents=True, exist_ok=True)

    world_log = LOGS / "world.log"

    probe_log = None
    probe = None
    if args.probe:
        probe_log = base / "probe.log"
        probe = subprocess.Popen(
            [str(PY), str(ROOT / "reverse" / "probes" / "client" / f"{args.probe}.py"),
             "--timeout", str(int(args.minutes * 60 + 120)), "--poll", "30"],
            cwd=ROOT,
            stdout=probe_log.open("wb"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        print(f"[night] probe {args.probe} pid={probe.pid} -> {probe_log}")

    run_log = base / "private-run.log"
    cmd = [str(PY), str(ROOT / "scripts" / "private-run.py"), "--settle", str(args.settle)]
    if args.no_launch:
        cmd.append("--no-launch")
    print("[night] driving private-run:", " ".join(cmd[-3:]))
    with run_log.open("wb") as fh:
        subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False)
    print("[night]", run_log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1])

    end = time.time() + args.minutes * 60
    shot_done = False
    while time.time() < end:
        time.sleep(60)
        left = int((end - time.time()) / 60)
        if not shot_done and left < args.minutes - 3:
            subprocess.run([str(PY), str(ROOT / "scripts" / "shot.py")], cwd=ROOT, check=False,
                           stdout=subprocess.DEVNULL)
            src = ROOT / ".azoth" / "captures" / "azoth_shot.png"
            if src.is_file():
                (base / "shot.png").write_bytes(src.read_bytes())
                subprocess.run([str(PY), str(ROOT / "scripts" / "shrink-image.py"),
                                str(base / "shot.png")], cwd=ROOT, check=False,
                               stdout=subprocess.DEVNULL)
            shot_done = True
        print(f"[night] {left} min left", flush=True)

    if probe and probe.poll() is None:
        # Graceful first: the probe's own --timeout should end it, and a hard kill of
        # the Frida host is suspected of taking the target with it. MEASURED 2026-10-11:
        # the clicontainer run's client process vanished at ~22 min with NO exit marker
        # in Game.log at all (no ActorContainerDisconnect, no Cleanup(), no crash report),
        # ~2 min after this script terminated the probe. Until that is settled, prefer
        # the graceful path and let the probe expire on its own timeout.
        probe.terminate()
        try:
            probe.wait(timeout=15)
        except subprocess.TimeoutExpired:
            probe.kill()

    summary = {
        "tag": args.tag,
        "started_utc": stamp,
        "env": {k: v for k, v in os.environ.items() if k.startswith("AZOTH_")},
        "world_events": count_events(world_log),
        "game_log": game_log_markers(),
        "probe_tail": (probe_log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                       if probe_log and probe_log.is_file() else []),
    }
    (base / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["game_log"], indent=2))
    print(json.dumps(summary["world_events"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
