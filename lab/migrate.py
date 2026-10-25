"""Move the old per-user Azoth AppData tree into this checkout."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from lab.env import PS, WINDOWS_HIDDEN, local_env
from lab.paths import LOGS, PRIVATE, ROOT


def _plan() -> list[tuple[Path, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    archive = ROOT / ".azoth" / "archive" / "legacy-appdata"
    return [
        (local / "AGS" / "New World", PRIVATE / "profile" / "Local" / "AGS" / "New World"),
        (roaming / "AGS" / "New World", PRIVATE / "profile" / "Roaming" / "AGS" / "New World"),
        (local / "Azoth" / "game", PRIVATE / "runtime"),
        (local / "Azoth" / "pakindex", ROOT / ".azoth" / "cache" / "pak-index"),
        (local / "Azoth" / "decomp", archive / "decomp"),
        (local / "Azoth" / "tools", archive / "tools"),
        (local / "Azoth" / "admin", archive / "admin"),
        (local / "Azoth" / "logs", LOGS / "archive" / "legacy-appdata"),
    ]


def _blockers() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    command = r"""
$legacy = Join-Path $env:LOCALAPPDATA 'Azoth'
$items = @(Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'NewWorld.exe' -or
  ($_.CommandLine -and $_.CommandLine.IndexOf($legacy, [StringComparison]::OrdinalIgnoreCase) -ge 0)
} | Select-Object @{n='pid';e={[string]$_.ProcessId}}, @{n='name';e={$_.Name}}, CommandLine)
ConvertTo-Json -InputObject $items -Compress
"""
    result = subprocess.run(
        [*PS, "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOWS_HIDDEN,
        env=local_env(),
    )
    if result.returncode:
        raise RuntimeError("could not check whether the old game/decompiler state is in use")
    raw = result.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        parsed = [parsed]
    return parsed


def migrate_appdata() -> int:
    if os.name != "nt":
        print("[ef] AppData migration is only available on Windows")
        return 2
    if not os.environ.get("LOCALAPPDATA") or not os.environ.get("APPDATA"):
        print("[ef] Windows did not provide both LOCALAPPDATA and APPDATA")
        return 1
    try:
        processes = _blockers()
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[ef] migration stopped before changing files: {exc}")
        return 1
    all_moves = _plan()
    plan = [(source, target) for source, target in all_moves if source.exists()]
    old_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Azoth"
    known = {source.name.casefold() for source, _ in all_moves if source.parent == old_root}
    if old_root.is_dir():
        archive = ROOT / ".azoth" / "archive" / "legacy-appdata" / "unclassified"
        plan.extend(
            (item, archive / item.name)
            for item in old_root.iterdir()
            if item.name.casefold() not in known
        )
    if not plan:
        print("[ef] no legacy AppData state found")
        return 0

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    live_client_sources = {
        local / "AGS" / "New World",
        roaming / "AGS" / "New World",
        local / "Azoth" / "game",
    }
    ready = []
    blocked = []
    conflicts = []
    for source, target in plan:
        if target.exists():
            conflicts.append((source, target, "destination already exists"))
            continue
        if source.drive.casefold() != target.drive.casefold():
            conflicts.append((source, target, "source and destination are on different drives"))
            continue
        reason = None
        for process in processes:
            if process["name"].casefold() == "newworld.exe" and source in live_client_sources:
                reason = f"{process['name']} (pid {process['pid']}) is using the live profile/runtime"
                break
            command_line = (process.get("CommandLine") or "").replace("/", "\\").casefold()
            source_name = str(source).replace("/", "\\").rstrip("\\").casefold()
            if source_name in command_line:
                reason = f"{process['name']} (pid {process['pid']}) is using this path"
                break
        if reason:
            blocked.append((source, target, reason))
        else:
            ready.append((source, target))

    moved = []
    try:
        for source, target in ready:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            moved.append(target.relative_to(ROOT))
    except OSError as exc:
        print(f"[ef] migration stopped after {len(moved)} move(s): {exc}")
        print("[ef] moved items are preserved in the checkout; rerun after resolving the error")
        return 1

    if old_root.is_dir():
        try:
            old_root.rmdir()
        except OSError:
            pass
    for target in moved:
        print(f"[ef] moved to {target}")
    for source, _target, reason in blocked:
        print(f"[ef] waiting: {source.name} stays in AppData; {reason}")
    for source, target, reason in conflicts:
        print(f"[ef] skipped: {source.name} -> {target.relative_to(ROOT)} ({reason})")
    return 1 if blocked or conflicts else 0
