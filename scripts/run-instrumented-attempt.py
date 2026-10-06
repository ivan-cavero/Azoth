#!/usr/bin/env python3
"""One-shot instrumented world attempt: launch game, attach early, verify burst.

Automates the full sequence so the record-1/possession burst never escapes
the probe window (it fires ~5 s after ClientContext::Initialize, and the
previous runs lost it by attaching minutes later):

  1. start the game via the managed launcher (python az.py game restart)
  2. attach reverse/probes/client/frida-record1-chain.py as soon as the window exists
  3. wait for the burst markers (record1 events) or a timeout
  4. report what was captured; the user then enters the world normally

Usage:
  python scripts/run-instrumented-attempt.py [--keep]   # --keep: leave the
      # probe running after the burst (default stops after the burst settles)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / ".azoth" / "captures" / "probes"
PYTHON = REPO / ".azoth" / "venv" / "Scripts" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)
os.environ["AZOTH_REPLAY_LOCAL_PLAYER_UUID"] = "character"


def game_pid() -> int | None:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq NewWorld.exe", "/FO", "CSV"],
        capture_output=True, text=True,
    ).stdout
    for line in out.splitlines()[1:]:
        cols = [c.strip('"') for c in line.split('","')]
        if cols and cols[0] == "NewWorld.exe":
            return int(cols[1])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--max-wait", type=int, default=420,
                    help="seconds to wait for the burst markers")
    args = ap.parse_args()

    # 1. launch
    print("[attempt] launching game (watch flow)...", flush=True)
    subprocess.Popen(
        [str(PYTHON), "az.py", "game", "restart"],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    # 2. attach as soon as the window exists
    pid = None
    for _ in range(60):
        pid = game_pid()
        if pid:
            break
        time.sleep(2)
    if not pid:
        print("[attempt] game never appeared")
        return 1
    print(f"[attempt] game pid {pid} — attaching probe early...", flush=True)
    time.sleep(4)  # let the module map enough for Interceptor.attach

    probe = subprocess.Popen(
        [str(PYTHON), "-u", str(REPO / "reverse" / "probes" / "client" / "frida-record1-chain.py"), "--stay"],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"[attempt] probe pid {probe.pid} attached early", flush=True)

    # 3. wait for burst markers in the newest session jsonl
    deadline = time.time() + args.max_wait
    log_path = None
    burst_events: list[dict] = []
    print("[attempt] waiting for the possession burst... enter the world when ready", flush=True)
    while time.time() < deadline:
        sessions = sorted(OUT_DIR.glob("record1-chain-*.jsonl"), key=os.path.getmtime)
        if sessions:
            log_path = sessions[-1]
            if log_path.exists():
                for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("ev") not in ("alive", "ready"):
                        if ev not in burst_events:
                            burst_events.append(ev)
        if burst_events:
            print(f"[attempt] BURST CAPTURED ({len(burst_events)} events):", flush=True)
            for ev in burst_events[:40]:
                print("   ", json.dumps(ev), flush=True)
            break
        time.sleep(2)
    else:
        print("[attempt] no burst events within the window", flush=True)

    # 4. report and either keep or stop the probe
    if burst_events and not args.keep:
        time.sleep(30)  # let the burst settle (manager/portrayal follow-ups)
        probe.terminate()
        print("[attempt] probe stopped after the burst", flush=True)
    else:
        print(f"[attempt] probe left running (pid {probe.pid})", flush=True)
    print(f"[attempt] evidence: {log_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
