#!/usr/bin/env python3
"""Start the SECOND private client against the same local server.

WHAT THIS IS: a preflight plus `scripts/private-run.py --instance 2`. Two
private clients can share one world server because the server keys its REP
sessions by (ip, port) -- `RepServer.peers: dict[(ip, port), PeerSession]` in
services/world/src/azoth_world/rep.py, asserted by
`test_rep.TestTwoClientsShareOneWorldServer`. This script only makes sure the
second launch cannot destroy the first client's evidence and cannot run an
unpatched executable.

What collides, and where each collision is handled:

  * Launcher state (`game.pid`, `eos.pid`, `client-source.json`, TEMP dir):
    per-instance directories in `Start-NwPrivate.ps1 -Instance N`.
  * `Game.log` and `savedata`: SHARED and unavoidable. The client resolves them
    through the Windows known-folder API and ignores the launcher's
    LOCALAPPDATA/APPDATA overrides (measured 2026-10-07, see
    research/docs/PRIVATE-CLIENT-RUNBOOK.md), so the second launch TRUNCATES the
    log the first client is writing. This script snapshots that log first, and
    the authoritative record of a two-client run is `.azoth/logs/world.log`,
    where every REP event carries its `peer` (ip:port).
  * The private executable is shared ON PURPOSE: one 179 MB copy in
    `private-client/runtime/Bin64/NewWorld.exe`, one DTLS disk patch, both
    clients. A per-instance runtime would need its own DTLS patch and
    `scripts/patch-dtls-disk.py` only patches the default path.

Usage:
  python scripts/run-second-client.py                # launch + drive client 2
  python scripts/run-second-client.py --no-launch    # drive a running client 2
  python scripts/run-second-client.py --no-play      # stop at character select
  python scripts/run-second-client.py --settle 90    # any other flag is passed
                                                    # through to private-run.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PRIVATE = REPO / "private-client"
PRIVATE_RUN = REPO / "scripts" / "session" / "private-run.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winwindow import game_pids  # noqa: E402


def read_pid(instance: int) -> int | None:
    base = PRIVATE / "state"
    pid_file = (base if instance == 1 else base / f"instance-{instance}") / "game.pid"
    try:
        return int(pid_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def check_dtls_patch() -> bool:
    """The shared private executable must carry the DTLS verify bypass (gate 4).

    Read the launcher's own record instead of re-hashing a 179 MB file: it stores
    both the Steam source hash and the hash it installed, so
    `runtimeSha256 != sourceSha256` means the copy on disk was modified -- which
    on this build is the DTLS disk patch. Both clients run that one file, so an
    unpatched copy fails BOTH clients with `tlsv1 alert unknown ca`.
    """
    record = PRIVATE / "state" / "client-source.json"
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("  [pre] no client-source.json yet; cannot verify the DTLS patch "
              "(the launcher writes it on the first launch)")
        return True
    source = str(data.get("sourceSha256") or data.get("sha256") or "")
    runtime = str(data.get("runtimeSha256") or "")
    if not runtime:
        # Older record: `mode` is the launcher's own answer.
        return data.get("mode") != "synced"
    return runtime != source


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", type=int, default=2,
                    help="which client to start (default 2)")
    args, passthrough = ap.parse_known_args()

    if args.instance < 2:
        print("[second] --instance must be 2 or greater; instance 1 is the existing client")
        return 2

    running = set(game_pids())
    first_pid = read_pid(1)
    if first_pid and first_pid in running:
        print(f"[second] client instance 1 is running (pid {first_pid}); its Game.log "
              "will be snapshotted before the second client truncates it")
    else:
        print("[second] no client instance 1 detected; the second client will start alone")

    if not check_dtls_patch():
        print("[second] FAIL: the private executable does not carry the DTLS disk patch. "
              "Both clients run that file, so run:\n"
              "  python scripts/patch-dtls-disk.py apply")
        return 1

    second_pid = read_pid(args.instance)
    if second_pid and second_pid in running:
        print(f"[second] client instance {args.instance} is already running (pid {second_pid}); "
              f"driving it with --no-launch")
        passthrough = ["--no-launch", *passthrough]

    command = [sys.executable, str(PRIVATE_RUN), "--instance", str(args.instance), *passthrough]
    print(f"[second] {' '.join(command[1:])}")
    return subprocess.run(command, cwd=REPO, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
