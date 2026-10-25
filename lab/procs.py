"""Pid files and process start/stop for the lab."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from lab.env import PS, WINDOWS_HIDDEN
from lab.paths import ROOT, STATE


def record_path(name: str) -> Path:
    return STATE / f"{name}.json"


def read_record(name: str) -> dict | None:
    try:
        return json.loads(record_path(name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_record(name: str, record: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    target = record_path(name)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def process_command(pid: int) -> str | None:
    if os.name == "nt":
        script = (
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
            "if ($p) { [Console]::WriteLine($p.CommandLine) }"
        )
        result = subprocess.run(
            [*PS, "-Command", script],
            capture_output=True,
            text=True,
            creationflags=WINDOWS_HIDDEN,
        )
        return result.stdout.strip() or None
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return None


def running(name: str, record: dict | None = None) -> bool:
    record = record or read_record(name)
    if not record:
        return False
    command = process_command(int(record["pid"]))
    marker = str(record.get("marker", ""))
    if command and marker.casefold() in command.casefold():
        return True
    record_path(name).unlink(missing_ok=True)
    return False


def start(name: str, command: list[str], cwd: Path, marker: str, log: Path,
          env: dict[str, str] | None = None) -> int:
    existing = read_record(name)
    if running(name, existing):
        print(f"[ef] {name} already running (pid {existing['pid']})")
        return 0

    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log.open("ab") as output:
            proc = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=WINDOWS_HIDDEN if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
    except OSError as exc:
        print(f"[ef] could not start {name}: {exc}")
        return 1
    time.sleep(0.25)
    if proc.poll() is not None:
        print(f"[ef] {name} exited during startup; see {log}")
        return int(proc.returncode or 1)
    write_record(name, {
        "pid": proc.pid,
        "marker": marker,
        "command": command,
        "cwd": str(cwd),
        "log": str(log),
        "started": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    print(f"[ef] {name} started (pid {proc.pid}); log: {log.relative_to(ROOT)}")
    return 0


def stop(name: str) -> bool:
    record = read_record(name)
    if not record:
        return False
    pid = int(record["pid"])
    marker = str(record.get("marker", ""))
    if not running(name, record):
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=WINDOWS_HIDDEN,
        )
        stopped = result.returncode == 0
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
            stopped = True
        except ProcessLookupError:
            stopped = False
    deadline = time.monotonic() + 10
    while stopped and time.monotonic() < deadline:
        command = process_command(pid)
        if not command or marker.casefold() not in command.casefold():
            break
        time.sleep(0.1)
    command = process_command(pid)
    if command and marker.casefold() in command.casefold():
        print(f"[ef] {name} is still running (pid {pid}); state record kept")
        return False
    record_path(name).unlink(missing_ok=True)
    print(f"[ef] {name} stopped (pid {pid})" if stopped else f"[ef] {name} was not running")
    return stopped
