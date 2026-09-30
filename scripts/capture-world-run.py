#!/usr/bin/env python3
"""Snapshot a game log and one REP DTLS session into ignored local evidence.

The shared REP JSONL is append-only and can be very large. This reads a
bounded snapshot, copies only the selected DTLS session, and leaves the live
capture untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REP_LOG = ROOT / "services" / "world" / "rep_traffic.jsonl"
GAME_LOG = Path(os.environ["LOCALAPPDATA"]) / "AGS" / "New World" / "Game.log"
EXE = Path(os.environ["LOCALAPPDATA"]) / "Azoth" / "game" / "Bin64" / "NewWorld.exe"
GATEWAY_LOG = Path(
    os.environ.get("AZOTH_TRAFFIC_JSONL")
    or ROOT / "services" / "gateway" / "traffic.jsonl"
)
GATEWAY_PAYLOADS = Path(
    os.environ.get("AZOTH_TRAFFIC_PAYLOAD_DIR") or GATEWAY_LOG.with_name("traffic-payloads")
)
SESSIONS = ROOT / "research" / "sessions"
BOUNDARY = b'"event": "dtls-established"'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="NewWorld.exe PID for this run")
    parser.add_argument("--session", type=int, default=-1, help="0-based DTLS session index; negative from newest")
    parser.add_argument("--screenshot", type=Path, help="optional already-shrunk .small.jpg screenshot")
    parser.add_argument("--burst-log", type=Path, help="optional JSONL output from frida-burst-capture.py")
    parser.add_argument("--slot-log", type=Path, help="optional JSONL output from frida-slot-watch.py")
    parser.add_argument("--deferred-log", type=Path, help="optional JSONL output from frida-deferred-actions.py")
    args = parser.parse_args()

    for path in (REP_LOG, GAME_LOG, EXE):
        if not path.is_file():
            parser.error(f"required file not found: {path}")
    if args.screenshot and (not args.screenshot.is_file() or not args.screenshot.name.endswith(".small.jpg")):
        parser.error("screenshot must be an existing .small.jpg; shrink it with scripts/shrink-image.py first")
    if args.burst_log and not args.burst_log.is_file():
        parser.error(f"burst log not found: {args.burst_log}")
    if args.slot_log and not args.slot_log.is_file():
        parser.error(f"slot log not found: {args.slot_log}")
    if args.deferred_log and not args.deferred_log.is_file():
        parser.error(f"deferred-action log not found: {args.deferred_log}")

    # Bound the read to the file size observed at start. The world server may
    # continue appending while this snapshot is made.
    rep_size = REP_LOG.stat().st_size
    sessions: list[tuple[int, int, dict]] = []
    pending_raw: dict[str, int] = {}
    with REP_LOG.open("rb") as src:
        while src.tell() < rep_size:
            offset = src.tell()
            line = src.readline(min(1024 * 1024, rep_size - offset))
            if not line:
                break
            if b'"event": "raw-datagram"' in line:
                try:
                    raw_event = json.loads(line)
                    pending_raw.setdefault(str(raw_event.get("peer", "")), offset)
                except (UnicodeDecodeError, ValueError):
                    pass
            if BOUNDARY in line:
                try:
                    event = json.loads(line)
                except (UnicodeDecodeError, ValueError):
                    continue
                peer = str(event.get("peer", ""))
                start = pending_raw.pop(peer, offset)
                sessions.append((start, offset, event))

    if not sessions:
        parser.error("no DTLS session boundaries in REP log")
    if not -len(sessions) <= args.session < len(sessions):
        parser.error(f"session index out of range; snapshot contains {len(sessions)} sessions")
    selected = args.session % len(sessions)
    start, boundary_offset, boundary = sessions[selected]
    end = sessions[selected + 1][1] if selected + 1 < len(sessions) else rep_size

    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out = SESSIONS / f"world_{stamp}_pid{args.pid}_session{selected}"
    out.mkdir(parents=True, exist_ok=False)

    shutil.copy2(GAME_LOG, out / "Game.log")
    with REP_LOG.open("rb") as src, (out / "rep_traffic.jsonl").open("wb") as dst:
        src.seek(start)
        remaining = end - start
        while remaining:
            chunk = src.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            dst.write(chunk)
            remaining -= len(chunk)

    if args.screenshot:
        shutil.copy2(args.screenshot, out / "screen.small.jpg")
    if args.burst_log:
        shutil.copy2(args.burst_log, out / "burst-capture.jsonl")
    if args.slot_log:
        shutil.copy2(args.slot_log, out / "slot-watch.jsonl")
    if args.deferred_log:
        shutil.copy2(args.deferred_log, out / "deferred-actions.jsonl")

    # Include HTTP records from this game-process run and copy only the exact
    # raw body sidecars they reference. Both files are append-only; bound reads
    # to their starting sizes and never edit the live gateway log.
    gateway_count = 0
    gateway_size = GATEWAY_LOG.stat().st_size if GATEWAY_LOG.is_file() else 0
    gateway_launch_ts = None
    gateway_payload_count = 0
    if gateway_size:
        with GAME_LOG.open("r", encoding="utf-8", errors="replace") as source:
            for line in source:
                if "Executable: NewWorld.exe" in line:
                    try:
                        gateway_launch_ts = line[1:20].replace(" ", "T") + "Z"
                    except IndexError:
                        continue

        if gateway_launch_ts:
            sidecars: set[str] = set()
            with GATEWAY_LOG.open("rb") as source, (out / "gateway_traffic.jsonl").open("wb") as target:
                remaining = gateway_size
                while remaining:
                    line = source.readline(min(1024 * 1024, remaining))
                    if not line:
                        break
                    remaining -= len(line)
                    try:
                        record = json.loads(line)
                    except (UnicodeDecodeError, ValueError):
                        continue
                    if str(record.get("ts", "")) < gateway_launch_ts:
                        continue
                    target.write(line if line.endswith(b"\n") else line + b"\n")
                    gateway_count += 1
                    payload_refs = record.get("raw_payloads")
                    if isinstance(payload_refs, dict):
                        for ref in payload_refs.values():
                            name = ref.get("file") if isinstance(ref, dict) else None
                            if isinstance(name, str) and Path(name).name == name:
                                sidecars.add(name)

            if sidecars:
                payload_out = out / "gateway_payloads"
                payload_out.mkdir()
                for name in sorted(sidecars):
                    source = GATEWAY_PAYLOADS / name
                    if source.is_file():
                        shutil.copy2(source, payload_out / name)
                        gateway_payload_count += 1

    ack = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ack-window.py"), "--session", str(selected)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "ack-window.txt").write_text(ack.stdout + ack.stderr, encoding="utf-8")

    exe_hash = hashlib.sha256()
    with EXE.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            exe_hash.update(chunk)
    metadata = {
        "captured_utc": now.isoformat(),
        "pid": args.pid,
        "process_image": str(EXE),
        "process_sha256": exe_hash.hexdigest(),
        "process_size": EXE.stat().st_size,
        "game_log": str(GAME_LOG),
        "rep_log": str(REP_LOG),
        "rep_snapshot_size": rep_size,
        "rep_session_index": selected,
        "rep_session_start_offset": start,
        "rep_dtls_boundary_offset": boundary_offset,
        "rep_session_end_offset": end,
        "rep_session_ts": boundary.get("ts"),
        "rep_peer": boundary.get("peer"),
        "ack_analysis_exit_code": ack.returncode,
        "gateway_log": str(GATEWAY_LOG),
        "gateway_snapshot_size": gateway_size,
        "gateway_launch_ts": gateway_launch_ts,
        "gateway_rows_copied": gateway_count,
        "gateway_payload_files_copied": gateway_payload_count,
        "burst_log_copied": bool(args.burst_log),
        "slot_log_copied": bool(args.slot_log),
        "deferred_log_copied": bool(args.deferred_log),
        "raw_capture_note": "Local ignored evidence; may contain private identities, tokens, HTTP bodies, and full plaintext payloads.",
    }
    (out / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
