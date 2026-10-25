"""Private client launch."""

from __future__ import annotations

import subprocess
import time
from datetime import datetime

from lab.env import WINDOWS_HIDDEN, launcher_shell, local_env
from lab.host import mode
from lab.paths import LOGS, PRIVATE, ROOT
from lab.procs import process_command, read_record, running, start, stop


def game_process_pid() -> int | None:
    try:
        return int((PRIVATE / "state" / "game.pid").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _stop_sidecar(filename: str, marker: str) -> None:
    pid_file = PRIVATE / "state" / filename
    try:
        pid = int(pid_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    command = process_command(pid)
    if command and marker.casefold() in command.casefold():
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=WINDOWS_HIDDEN,
        )
    pid_file.unlink(missing_ok=True)


def private_client_running() -> bool:
    pid = game_process_pid()
    if pid is None:
        return False
    command = process_command(pid)
    exe = str((PRIVATE / "runtime" / "Bin64" / "NewWorld.exe")).casefold()
    return bool(command and exe in command.casefold())


def game_action(action: str, args: list[str]) -> int:
    record = read_record("game")
    supervisor_up = running("game", record)
    client_up = private_client_running()
    if action == "status":
        if supervisor_up or client_up:
            print(f"game: running (client pid {game_process_pid() or 'unknown'})")
        else:
            print("game: stopped")
        return 0
    if action == "stop":
        stop("game")
        _stop_sidecar("eos.pid", "frida-eos-stub.py")
        pid = game_process_pid()
        if pid and private_client_running():
            subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=WINDOWS_HIDDEN,
            )
            print(f"[ef] private client stopped (pid {pid})")
        (PRIVATE / "state" / "game.pid").unlink(missing_ok=True)
        return 0
    if action == "restart":
        game_action("stop", [])
        time.sleep(1)
        return game_action("start", args)
    if action != "start":
        print("usage: python ef.py game [start|stop|restart|status] [--install <path>]")
        return 2
    if supervisor_up or client_up:
        print("[ef] private client already running; use `python ef.py game restart`")
        return 0
    if mode(["status"]):
        print("[ef] private host routing is not active; switch it before launching the private client")
        return 2
    if not (ROOT / ".azoth" / "venv" / "Scripts" / "python.exe").is_file():
        print("[ef] local tools are not installed; run `python ef.py setup` first")
        return 2
    launcher = ROOT / "services" / "launcher" / "src" / "Start-NwPrivate.ps1"
    command = [
        launcher_shell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(launcher), "-Watch",
    ]
    if args:
        if len(args) != 2 or args[0] != "--install":
            print("usage: python ef.py game [start|stop|restart|status] [--install <path>]")
            return 2
        command.extend(["-InstallRoot", args[1]])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return start(
        "game", command, ROOT,
        "Start-NwPrivate.ps1",
        LOGS / f"game-{stamp}.log",
        local_env(),
    )


def status() -> int:
    from lab.services import service_action

    for name in ("caddy", "gateway", "world", "game"):
        if name == "game":
            game_action("status", [])
        else:
            service_action(name, "status")
    return 0
