"""A/B a getlogininfo shape against the live client, end to end.

Writes the override, restarts the game, waits for the character panel, then OCRs
the world-dropdown row and reports whether the world name shows up. One shape per
run (~2 min) because the panel only consumes getlogininfo at login: hot-swapping
the override and waiting for the next poll does NOT re-render it.

Usage:
  python scripts/try-world-shape.py --root worlds
  python scripts/try-world-shape.py --file /path/to/body.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
OVERRIDE = REPO / "emulator/apps/gateway/mock_discovery/getlogininfo.json"
GAME_LOG = Path.home() / "AppData/Local/AGS/New World/Game.log"
GW_LOG = REPO / "emulator/apps/gateway/gateway.out.log"
ROW_PNG = Path.home() / "AppData/Local/Temp/azoth-ocr/row.png"
WORLD_ID = "00000000-0000-4000-8000-000000000001"
LAUNCHER = r"& 'C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\launcher\src\Start-NwPrivate.ps1'"

# Exact WorldMetadata property set, in registration order, from the AZ reflection
# table at 0x144f54cda (research xrefmap dump). Extra keys are not just ignored:
# a strict deserialize can drop the whole object.
WORLD_METADATA = {
    "worldId": WORLD_ID,
    "status": "ACTIVE",
    "publicStatusCode": 0,
    "maxAccountCharacters": 4,
    "worldSet": "azoth-1",
    "worldMetrics": {
        "worldAgeDays": 1,
        "queueSize": 0,
        "queueWaitTimeSec": 0,
        "worldPopulationStatus": "LOW",
    },
    "transferToRegion": "",
    "isRecommended": True,
}


def safe(text: str) -> str:
    """Panel OCR carries non-cp1252 glyphs; never let a print kill the run."""
    enc = sys.stdout.encoding or "utf-8"
    return text.encode(enc, errors="replace").decode(enc, errors="replace")


def body_for(root: str) -> dict:
    """One root key only: the parser is strict, an unexpected member can abort it."""
    if root == "WorldsInfo":
        return {"WorldsInfo": {"worlds": [WORLD_METADATA], "recommendedWorlds": []}}
    if root == "worldsInfo":
        return {"worldsInfo": {"worlds": [WORLD_METADATA], "recommendedWorlds": []}}
    if root == "worlds":
        return {"worlds": [WORLD_METADATA], "recommendedWorlds": []}
    if root in ("LoginInfoList", "loginInfoList", "Worlds"):
        return {root: [WORLD_METADATA]}
    raise SystemExit(f"unknown root {root!r}")


def restart_game() -> None:
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process NewWorld -ErrorAction SilentlyContinue | Stop-Process -Force",
        ],
        check=False,
        capture_output=True,
    )
    time.sleep(3)
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", LAUNCHER],
        check=False,
        capture_output=True,
    )


def poll_count() -> int:
    """How many times the client fetched getlogininfo. Proves the body was
    actually consumed: the panel only reads it during login."""
    try:
        return GW_LOG.read_text(encoding="utf-8", errors="replace").count(
            "-> getlogininfo mock"
        )
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


def wait_for_login(marker: int, timeout: float = 150) -> bool:
    """True only when CampfireLoginComplete appears after THIS run's start."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            text = GAME_LOG.read_text(encoding="utf-8", errors="replace")
        except OSError:
            time.sleep(3)
            continue
        if text.rfind("Executable: NewWorld.exe") != marker:
            return False  # another launch superseded us
        if "CampfireLoginComplete" in text[marker:]:
            return True
        time.sleep(3)
    return False


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


def row_text(y0: int = 0, y1: int = 712) -> str:
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
    ap.add_argument("--root")
    ap.add_argument("--file", type=Path)
    ap.add_argument(
        "--raw",
        action="store_true",
        help="serve the file bytes verbatim (no JSON parse)",
    )
    args = ap.parse_args()

    if args.file and args.raw:
        try:
            raw = args.file.read_bytes()
        except OSError as exc:
            raise SystemExit(f"cannot read {args.file}: {exc}") from exc
        OVERRIDE.write_bytes(raw)
        label = f"raw:{args.file.name}"
    else:
        if args.file:
            try:
                doc = json.loads(args.file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SystemExit(f"cannot read shape file {args.file}: {exc}") from exc
            label = f"file:{args.file.name}"
        elif args.root:
            doc = body_for(args.root)
            label = f"root={args.root}"
        else:
            raise SystemExit("pass --root or --file")
        OVERRIDE.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    print(f"[shape] {label}", flush=True)

    restart_game()
    marker = session_marker()
    ok = wait_for_login(marker)
    polls = poll_count()
    print(
        f"[login] CampfireLoginComplete={ok} | getlogininfo polls={polls}", flush=True
    )

    text = advance_to_panel()
    row = row_text()
    print(f"[row] {safe(row).replace(chr(10), ' | ')}", flush=True)
    hit = "Azoth-1" in text or "azoth-1-01" in text or "azoth-1-01" in row.lower()
    print(f"[RESULT] {label} -> world visible: {hit}", flush=True)
    return 0 if hit else 1


if __name__ == "__main__":
    raise SystemExit(main())
