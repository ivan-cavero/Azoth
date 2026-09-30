#!/usr/bin/env python3
"""az — single entry point for every Azoth operation.

Examples:
  python az.py gateway start     # gateway :8080 in a new window
  python az.py dev               # ONE console: gateway+world hot-reload, caddy if needed
  python az.py dev stop          # kill every Azoth service (game untouched)
  python az.py gateway test      # gateway unit tests (17)
  python az.py world start       # Javelin REP/DTLS server :9000 in a new window
  python az.py world test        # world unit tests (javelin + DTLS handshake)
  python az.py caddy             # Caddy :443 (elevates via UAC)
  python az.py game              # launch New World private (watch mode)
  python az.py mode status       # hosts mode: official | private
  python az.py click 960 540     # synthetic click in the game window (steals mouse/focus)
  python az.py post click 960 540  # background click via PostMessage (NO mouse/focus steal)
  python az.py post key 1B       # background key (VK hex), same channel
  python az.py shot              # screenshot the game window to %TEMP%\azoth_shot.png
  python az.py shape <file.json> # A/B test a getlogininfo body end-to-end
  python az.py run <script> ...  # passthrough to any scripts/ tool

Everything resolves paths relative to this file. No hard-coded drives.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
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


def port_open(host: str, port: int, udp: bool = False) -> bool:
    """True when something already listens on host:port. LESSONS.md #9:
    duplicated service processes are the #1 time sink — start is idempotent
    and refuses to launch a second instance.

    World is UDP: a TCP connect to :9000 always fails, so without `udp`
    we would start a second REP server on every `az.py world start`.
    """
    import socket

    if udp:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((host, port))
        except OSError:
            return True
        finally:
            s.close()
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


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
    port = int(args[1]) if len(args) > 1 else 8080
    if port_open("127.0.0.1", port):
        print(f"[az] gateway already listening on :{port} — not starting a second one")
        return 0
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
                print(
                    f"[az] change: {changed[0].name} - restarting gateway", flush=True
                )
                proc.terminate()
                proc.wait(timeout=5)
                proc = subprocess.Popen(
                    [sys.executable, "-u", "-m", "azoth_gateway", "--port", "8080"],
                    env=env,
                )
                last = now
    except KeyboardInterrupt:
        proc.terminate()
    return 0


def cmd_doc(_args: list[str]) -> int:
    """Generate research/atlas/openapi.json from captured traffic."""
    return subprocess.call([sys.executable, str(SCRIPTS / "gen_openapi.py")])


def cmd_world(args: list[str]) -> int:
    action = args[0] if args else "start"
    src = ROOT / "services" / "world" / "src"
    if action == "test":
        return sh([sys.executable, str(ROOT / "services" / "world" / "tests" / "test_javelin.py")]) + sh(
            [sys.executable, str(ROOT / "services" / "world" / "tests" / "test_rep.py")]
        )
    if action != "start":
        print(__doc__)
        return 2
    port = int(args[1]) if len(args) > 1 else 9000
    if port_open("127.0.0.1", port, udp=True):
        print(f"[az] world already listening on :{port} — not starting a second one")
        return 0
    cmd = f"$env:PYTHONPATH='{src}'; python -u -m azoth_world --port {port}"
    return ps_window(cmd, "Azoth World")


AZOTH_PROCS = (
    r"azoth_gateway",
    r"azoth_world",
    r"frida-eos-stub",
    r"frida-trust-patch",
    r"frida-anticheat-patch",
    r"frida-rep-force-ladder",
)


def kill_azoth_services() -> None:
    """Kill every Azoth service by command line (LESSONS: duplicated
    processes are the #1 time sink). Does NOT touch NewWorld.exe."""
    wmic = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
        + "'(" + "|".join(AZOTH_PROCS) + ")' "
        + "-or $_.CommandLine -like '*Azoth Gateway*' -or $_.CommandLine -like '*Azoth World*' "
        + "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.call([*PS, "-Command", wmic], creationflags=0x08000000)


def _supervise(name: str, args: list[str], watch_dir: Path, env: dict) -> None:
    """Run one service in this console; restart on any .py change."""
    import time as _time

    def snapshot():
        return {
            p: p.stat().st_mtime
            for p in watch_dir.rglob("*.py")
            if "__pycache__" not in p.parts
        }

    last = snapshot()

    def spawn():
        return subprocess.Popen(
            [sys.executable, "-u", *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    proc = spawn()

    def pump() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            print(f"[{name}] {line}", end="", flush=True)

    import threading

    threading.Thread(target=pump, daemon=True).start()
    print(f"[dev] {name} up (hot-reload on {watch_dir})", flush=True)
    while True:
        _time.sleep(1)
        if proc.poll() is not None:
            print(f"[dev] {name} exited ({proc.returncode}) — restarting", flush=True)
            proc = spawn()
            threading.Thread(target=pump, daemon=True).start()
            last = snapshot()
            continue
        now = snapshot()
        if now != last:
            changed = [p for p, m in now.items() if last.get(p) != m]
            print(f"[dev] {name} change: {changed[0].name} — restarting", flush=True)
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
            proc = spawn()
            threading.Thread(target=pump, daemon=True).start()
            last = now


def cmd_dev(args: list[str]) -> int:
    """`python az.py dev` — ONE console for the whole dev stack.

    Kills stale Azoth services, then supervises gateway (:8080) and world
    (:9000) with hot-reload in this terminal. Caddy (:443) needs admin:
    if it is not listening we start it elevated once (UAC) and leave it —
    its config never changes in a session. Only the game needs restarting
    by hand (`python az.py game`). `python az.py dev stop` kills it all.
    """
    import threading

    action = args[0] if args else "up"
    if action == "stop":
        kill_azoth_services()
        print("[dev] all Azoth services killed (game untouched)")
        return 0
    kill_azoth_services()
    time.sleep(1)
    if not port_open("127.0.0.1", 443):
        print("[dev] Caddy not listening on :443 — starting elevated (accept UAC)")
        subprocess.Popen([*PS, "-Command", "python az.py caddy"], cwd=str(ROOT))
        time.sleep(3)
    threads = []
    specs = [
        (
            "gateway",
            ["-m", "azoth_gateway", "--port", "8080"],
            ROOT / "services" / "gateway" / "src",
            {"PYTHONPATH": str(ROOT / "services" / "gateway" / "src")},
        ),
        (
            "world",
            ["-m", "azoth_world", "--port", "9000"],
            ROOT / "services" / "world" / "src",
            {"PYTHONPATH": str(ROOT / "services" / "world" / "src")},
        ),
    ]
    for name, margs, wdir, env in specs:
        t = threading.Thread(
            target=_supervise,
            args=(name, margs, wdir, {**os.environ, **env}),
            daemon=True,
        )
        t.start()
        threads.append(t)
    print("[dev] stack up — Ctrl+C stops everything (game keeps running)", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[dev] stopping...")
        kill_azoth_services()
    return 0


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
    if head == "dev":
        return cmd_dev(rest)
    if head == "world":
        return cmd_world(rest)
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
    if head == "post" and rest:
        return sh([sys.executable, str(SCRIPTS / "post-input.py"), *rest])
    if head == "shot":
        return sh([sys.executable, str(SCRIPTS / "shot.py"), *rest])
    if head == "key" and rest:
        return sh([sys.executable, str(SCRIPTS / "send-input.py"), *rest])
    if head == "run" and rest:
        return cmd_passthrough(rest[0], rest[1:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
