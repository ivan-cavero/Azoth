"""A/B a getlogininfo shape against the live client, end to end.

Writes the override, restarts the game, waits for the character panel, then OCRs
the world-dropdown row and reports whether the world name shows up. One shape per
run (~2 min) because the panel only consumes getlogininfo at login: hot-swapping
the override and waiting for the next poll does NOT re-render it.

Usage:
  python az.py shape /path/to/body.json
  python az.py shape /path/to/raw-response.bin --raw
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
SCRIPTS = REPO / "scripts"
OVERRIDE = REPO / "services/gateway/mock_discovery/getlogininfo.json"
# The game ignores the launcher's LOCALAPPDATA override and resolves its profile
# through the Windows known-folder API, so Game.log is under the real profile.
# See research/docs/PRIVATE-CLIENT-RUNBOOK.md (evidence paths).
GAME_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "AGS" / "New World" / "Game.log"
GW_LOG = REPO / ".azoth/logs/gateway.log"


def safe(text: str) -> str:
    """Panel OCR carries non-cp1252 glyphs; never let a print kill the run."""
    enc = sys.stdout.encoding or "utf-8"
    return text.encode(enc, errors="replace").decode(enc, errors="replace")


def restart_game() -> None:
    python = REPO / ".azoth/venv/Scripts/python.exe"
    if not python.is_file():
        python = Path(sys.executable)
    subprocess.run(
        [str(python), str(REPO / "az.py"), "game", "restart"],
        check=True,
        cwd=REPO,
    )


def log_offset(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def poll_count(offset: int) -> int:
    """Count only getlogininfo requests appended by this trial."""
    try:
        with GW_LOG.open("rb") as log:
            log.seek(offset)
            return log.read().count(b"-> getlogininfo mock")
    except OSError:
        return 0


def session_marker() -> int:
    """Offset of the current game session's start, so stale log lines from a
    previous run can never be mistaken for this run's login."""
    try:
        text = GAME_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return text.rfind("Executable: NewWorld.exe")


def wait_for_login(previous_marker: int, timeout: float = 150) -> bool:
    """Wait for this launch's start and completion, ignoring older log runs."""
    start = time.time()
    current_marker = None
    while time.time() - start < timeout:
        try:
            text = GAME_LOG.read_text(encoding="utf-8", errors="replace")
        except OSError:
            time.sleep(3)
            continue
        latest_marker = text.rfind("Executable: NewWorld.exe")
        if latest_marker < 0:
            time.sleep(3)
            continue
        if latest_marker != previous_marker:
            if current_marker is None:
                current_marker = latest_marker
            elif latest_marker != current_marker:
                return False  # another launch superseded this trial
            if "CampfireLoginComplete" in text[current_marker:]:
                return True
        time.sleep(3)
    return False


def replace_override(payload: bytes) -> None:
    temporary = OVERRIDE.with_name(OVERRIDE.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(OVERRIDE)
    finally:
        temporary.unlink(missing_ok=True)


def run_trial(payload: bytes, label: str) -> int:
    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    previous_override = OVERRIDE.read_bytes() if OVERRIDE.is_file() else None
    previous_game_marker = session_marker()
    gateway_offset = log_offset(GW_LOG)
    try:
        replace_override(payload)
        print(f"[shape] {label}", flush=True)

        restart_game()
        ok = wait_for_login(previous_game_marker)
        polls = poll_count(gateway_offset)
        print(
            f"[login] CampfireLoginComplete={ok} | getlogininfo polls={polls}",
            flush=True,
        )

        text = advance_to_panel()
        row = row_text()
        print(f"[row] {safe(row).replace(chr(10), ' | ')}", flush=True)
        hit = "Azoth-1" in text or "azoth-1-01" in text or "azoth-1-01" in row.lower()
        print(f"[RESULT] {label} -> world visible: {hit}", flush=True)
        return 0 if hit else 1
    finally:
        if previous_override is None:
            OVERRIDE.unlink(missing_ok=True)
        else:
            replace_override(previous_override)


def ocr_paths() -> list[str]:
    """Use orca's own screenshot: it reliably captures the game window, while
    ImageGrab depends on the window being foreground (flaky)."""
    r = subprocess.run(
        [
            "orca",
            "computer",
            "get-app-state",
            "--app",
            "NewWorld",
            "--restore-window",
            "--json",
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )
    try:
        shot = (
            json.loads(r.stdout or "{}").get("result", {}).get("screenshot") or {}
        ).get("path")
    except (ValueError, TypeError):
        shot = None
    return [shot] if shot else []


def ocr_text(paths: list[str]) -> str:
    seen: list[str] = []
    for path in paths:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPTS / "ocr-image.ps1"),
                path,
            ],
            capture_output=True,
            text=True,
            errors="replace",
        )
        seen.extend((r.stdout or "").splitlines())
    return "\n".join(seen)


def full_text() -> str:
    return ocr_text(ocr_paths())


def row_text() -> str:
    """The world-table region. Coordinates are ignored: the orca capture is
    scaled, so we OCR the full frame and filter by content downstream."""
    return ocr_text(ocr_paths())


def advance_to_panel(timeout: float = 240) -> str:
    """Wait for the title to be up, press Return once, then wait for the panel."""
    text = ""
    deadline = time.time() + timeout
    pressed = False
    while time.time() < deadline:
        text = full_text()
        up = text.upper()
        if any(k in up for k in ("ELEGIR", "MUNDOS", "REGI", "AZOTH")):
            return text
        if not pressed and any(
            k in up for k in ("BOTON", "CUALQUIER", "AETER", "AETERNUM")
        ):
            subprocess.run(
                [
                    "orca",
                    "computer",
                    "press-key",
                    "--app",
                    "NewWorld",
                    "--key",
                    "Return",
                    "--restore-window",
                    "--json",
                ],
                capture_output=True,
            )
            pressed = True
        time.sleep(12)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("body", type=Path, help="response body to try")
    ap.add_argument(
        "--raw",
        action="store_true",
        help="serve the file bytes verbatim (no JSON parse)",
    )
    args = ap.parse_args()

    if args.raw:
        try:
            raw = args.body.read_bytes()
        except OSError as exc:
            raise SystemExit(f"cannot read {args.body}: {exc}") from exc
        payload = raw
        label = f"raw:{args.body.name}"
    else:
        try:
            doc = json.loads(args.body.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot read shape file {args.body}: {exc}") from exc
        label = f"file:{args.body.name}"
        payload = (json.dumps(doc, indent=1) + "\n").encode("utf-8")
    return run_trial(payload, label)


if __name__ == "__main__":
    raise SystemExit(main())
