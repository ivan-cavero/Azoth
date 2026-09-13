#!/usr/bin/env python3
"""az — single entry point for every Azoth operation.

Examples:
  python az.py gateway start     # gateway :8080 in a new window
  python az.py gateway test      # gateway unit tests (17)
  python az.py caddy             # Caddy :443 (elevates via UAC)
  python az.py game              # launch New World private (watch mode)
  python az.py mode status       # hosts mode: official | private
  python az.py click 960 540     # synthetic click in the game window (orca cannot reach the game; SendInput can)
  python az.py key Return        # synthetic key press
  python az.py shape <file.json> # A/B test a getlogininfo body end-to-end
  python az.py run <script> ...  # passthrough to any scripts/ tool

Everything resolves paths relative to this file. No hard-coded drives.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]


def sh(args: list[str], window: bool = False) -> int:
    if window and sys.platform == "win32":
        subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return 0
    return subprocess.call(args)


def ps_window(command: str, title: str) -> int:
    cmd = f"$host.UI.RawUI.WindowTitle='{title}'; {command}"
    return sh([*PS, "-NoExit", "-Command", cmd], window=True)


def cmd_gateway(args: list[str]) -> int:
    action = args[0] if args else "start"
    src = ROOT / "services" / "gateway" / "src"
    if action == "test":
        tests = ROOT / "services" / "gateway" / "tests" / "test_gateway.py"
        return sh([sys.executable, str(tests)])
    if action == "reload":
        return cmd_gateway_reload()
    if action == "stop":
        subprocess.call(
            [
                "taskkill",
                "/F",
                "/IM",
                "python.exe",
                "/FI",
                "WINDOWTITLE eq Azoth Gateway*",
            ],
            creationflags=0x08000000,
        )
        return 0
    if action != "start":
        print(__doc__)
        return 2
    port = args[1] if len(args) > 1 else "8080"
    cmd = f"$env:PYTHONPATH='{src}'; python -m azoth_gateway --port {port}"
    return ps_window(cmd, "Azoth Gateway")


def cmd_gateway_reload() -> int:
    """Dev mode: run the gateway in this console, restart on any .py change."""
    import time

    src = ROOT / "services" / "gateway" / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}

    def snapshot():
        return {
            p: p.stat().st_mtime
            for p in src.rglob("*.py")
            if "__pycache__" not in p.parts
        }

    last = snapshot()
    print(f"[az] hot-reload watching {src} (Ctrl+C to stop)", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "azoth_gateway", "--port", "8080"], env=env
    )
    try:
        while True:
            time.sleep(1)
            now = snapshot()
            if now != last:
                changed = [p for p, m in now.items() if last.get(p) != m]
                print(f"[az] change: {changed[0].name} - restarting gateway", flush=True)
                proc.terminate()
                proc.wait(timeout=5)
                proc = subprocess.Popen(
                    [sys.executable, "-u", "-m", "azoth_gateway", "--port", "8080"], env=env
                )
                last = now
    except KeyboardInterrupt:
        proc.terminate()
    return 0


def cmd_doc(_args: list[str]) -> int:
    """Generate research/atlas/openapi.json from captured traffic."""
    return subprocess.call([sys.executable, str(SCRIPTS / "gen_openapi.py")])


def cmd_caddy(_args: list[str]) -> int:
    exe = ROOT / "deploy" / "bin" / "caddy.exe"
    cfg = ROOT / "deploy" / "Caddyfile.json"
    if (
        sys.platform == "win32"
        and subprocess.call(["net", "session"], creationflags=0x08000000) != 0
    ):
        return subprocess.call(
            [
                *PS,
                "-Command",
                f"Start-Process -FilePath '{exe}' -ArgumentList 'run','--config','{cfg}' -Verb RunAs",
            ]
        )
    return ps_window(f"& '{exe}' run --config '{cfg}'", "Azoth Caddy")


def cmd_game(_args: list[str]) -> int:
    launcher = ROOT / "services" / "launcher" / "src" / "Start-NwPrivate.ps1"
    return ps_window(f"& '{launcher}' -Watch", "Azoth Game")


def cmd_mode(args: list[str]) -> int:
    mode = args[0] if args else "status"
    return sh([*PS, "-File", str(ROOT / "deploy" / "switch-mode.ps1"), mode])


def cmd_shape(args: list[str]) -> int:
    if not args:
        print("usage: python az.py shape <body.json>")
        return 2
    return sh([sys.executable, str(SCRIPTS / "try-world-shape.py"), *args])


def cmd_passthrough(name: str, args: list[str]) -> int:
    script = SCRIPTS / name
    if not script.exists():
        print(f"unknown script: {name}")
        return 2
    return sh([sys.executable, str(script), *args])


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    head, rest = argv[0], argv[1:]
    if head == "gateway":
        return cmd_gateway(rest)
    if head == "doc":
        return cmd_doc(rest)
    if head == "caddy":
        return cmd_caddy(rest)
    if head == "game":
        return cmd_game(rest)
    if head == "mode":
        return cmd_mode(rest)
    if head == "shape":
        return cmd_shape(rest)
    if head == "click" and len(rest) == 2:
        return sh([sys.executable, str(SCRIPTS / "click-window.py"), *rest])
    if head == "key" and rest:
        return sh([sys.executable, str(SCRIPTS / "send-input.py"), *rest])
    if head == "run" and rest:
        return cmd_passthrough(rest[0], rest[1:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
