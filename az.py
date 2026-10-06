#!/usr/bin/env python3
"""One command surface for the local Azoth stack.

  python az.py setup              # install the locked local toolchain
  python az.py migrate            # move existing AppData state into this checkout
  python az.py dev                # gateway, world and Caddy in the background
  python az.py dev stop           # stop the server stack
  python az.py game               # launch the private client without a console
  python az.py game restart       # cleanly replace the private client
  python az.py status             # inspect managed processes
  python az.py stop               # stop all Azoth-managed processes
  python az.py gateway test       # run gateway checks
  python az.py world test         # run world checks
  python az.py mode status        # show official/private routing
  python az.py re list            # list maintained RE workflows
  python az.py re decompile ...   # focused native analysis
  python az.py re corpus ...      # full build-specific pseudocode pass
  python az.py re campaign ...    # incremental phase-scoped decompilation
  python az.py probe <name>       # run a client reverse-engineering probe
  python az.py run <script> ...   # run a focused scripts/ tool

Runtime files, PIDs and logs live under ignored project-local directories.
"""

from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
STATE = ROOT / ".azoth" / "state"
LOGS = ROOT / ".azoth" / "logs"
PRIVATE = ROOT / "private-client"
TMP = ROOT / ".azoth" / "tmp"
PS = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]
WINDOWS_HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def app_python() -> str:
    """Use the repo-local environment after setup, with system Python as bootstrap."""
    candidate = ROOT / ".azoth" / "venv" / "Scripts" / "python.exe"
    return str(candidate) if candidate.is_file() else sys.executable


def local_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Keep subprocess scratch data with the checkout instead of user temp."""
    TMP.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = str(TMP)
    env["TMP"] = str(TMP)
    env["PIP_CACHE_DIR"] = str(ROOT / ".azoth" / "cache" / "pip")
    if overrides:
        env.update(overrides)
    return env


def _appdata_migration_plan() -> list[tuple[Path, Path]]:
    """Map the old per-user runtime into ignored, project-local state."""
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


def _appdata_migration_blockers() -> list[dict[str, str]]:
    """Do not move a profile or Ghidra workspace while a process is using it."""
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


def _migrate_appdata() -> int:
    if os.name != "nt":
        print("[az] AppData migration is only available on Windows")
        return 2
    if not os.environ.get("LOCALAPPDATA") or not os.environ.get("APPDATA"):
        print("[az] Windows did not provide both LOCALAPPDATA and APPDATA")
        return 1
    try:
        processes = _appdata_migration_blockers()
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[az] migration stopped before changing files: {exc}")
        return 1
    all_moves = _appdata_migration_plan()
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
        print("[az] no legacy AppData state found")
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
        print(f"[az] migration stopped after {len(moved)} move(s): {exc}")
        print("[az] moved items are preserved in the checkout; rerun after resolving the error")
        return 1

    if old_root.is_dir():
        try:
            old_root.rmdir()
        except OSError:
            pass
    for target in moved:
        print(f"[az] moved to {target}")
    for source, target, reason in blocked:
        print(f"[az] waiting: {source.name} stays in AppData; {reason}")
    for source, target, reason in conflicts:
        print(f"[az] skipped: {source.name} -> {target.relative_to(ROOT)} ({reason})")
    return 1 if blocked or conflicts else 0


def _record_path(name: str) -> Path:
    return STATE / f"{name}.json"


def _read_record(name: str) -> dict | None:
    try:
        return json.loads(_record_path(name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_record(name: str, record: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    target = _record_path(name)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _process_command(pid: int) -> str | None:
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


def _running(name: str, record: dict | None = None) -> bool:
    record = record or _read_record(name)
    if not record:
        return False
    command = _process_command(int(record["pid"]))
    marker = str(record.get("marker", ""))
    if command and marker.casefold() in command.casefold():
        return True
    _record_path(name).unlink(missing_ok=True)
    return False


def _start(name: str, command: list[str], cwd: Path, marker: str, log: Path,
           env: dict[str, str] | None = None) -> int:
    existing = _read_record(name)
    if _running(name, existing):
        print(f"[az] {name} already running (pid {existing['pid']})")
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
        print(f"[az] could not start {name}: {exc}")
        return 1
    time.sleep(0.25)
    if proc.poll() is not None:
        print(f"[az] {name} exited during startup; see {log}")
        return int(proc.returncode or 1)
    _write_record(name, {
        "pid": proc.pid,
        "marker": marker,
        "command": command,
        "cwd": str(cwd),
        "log": str(log),
        "started": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    print(f"[az] {name} started (pid {proc.pid}); log: {log.relative_to(ROOT)}")
    return 0


def _stop(name: str) -> bool:
    record = _read_record(name)
    if not record:
        return False
    pid = int(record["pid"])
    marker = str(record.get("marker", ""))
    if not _running(name, record):
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
        command = _process_command(pid)
        if not command or marker.casefold() not in command.casefold():
            break
        time.sleep(0.1)
    command = _process_command(pid)
    if command and marker.casefold() in command.casefold():
        print(f"[az] {name} is still running (pid {pid}); state record kept")
        return False
    _record_path(name).unlink(missing_ok=True)
    print(f"[az] {name} stopped (pid {pid})" if stopped else f"[az] {name} was not running")
    return stopped


def _service_command(name: str) -> tuple[list[str], Path, str, Path, dict[str, str] | None]:
    python = app_python()
    if name == "gateway":
        src = ROOT / "services" / "gateway" / "src"
        return (
            [python, "-u", "-m", "azoth_gateway", "--port", "8080"],
            ROOT,
            "azoth_gateway",
            LOGS / "gateway.log",
            local_env({"PYTHONPATH": str(src)}),
        )
    if name == "world":
        src = ROOT / "services" / "world" / "src"
        return (
            [python, "-u", "-m", "azoth_world", "--port", "9000"],
            ROOT,
            "azoth_world",
            LOGS / "world.log",
            local_env({"PYTHONPATH": str(src)}),
        )
    if name == "caddy":
        exe = ROOT / "deploy" / "bin" / "caddy.exe"
        config = ROOT / "deploy" / "Caddyfile.json"
        if not exe.is_file():
            raise FileNotFoundError("Caddy is missing; run `python az.py setup` first")
        env = local_env({
            "XDG_DATA_HOME": str(ROOT / ".azoth" / "caddy" / "data"),
            "XDG_CONFIG_HOME": str(ROOT / ".azoth" / "caddy" / "config"),
        })
        return (
            [str(exe), "run", "--config", str(config)],
            ROOT / "deploy",
            str(exe),
            LOGS / "caddy.log",
            env,
        )
    raise ValueError(name)


def _service_action(name: str, action: str) -> int:
    if action == "status":
        record = _read_record(name)
        if _running(name, record):
            print(f"{name}: running (pid {record['pid']}, log {record['log']})")
        else:
            print(f"{name}: stopped")
        return 0
    if action == "stop":
        _stop(name)
        return 0
    if action == "restart":
        _stop(name)
    if action != "start" and action != "restart":
        print(f"usage: python az.py {name} [start|stop|restart|status|test]")
        return 2
    try:
        command, cwd, marker, log, env = _service_command(name)
    except OSError as exc:
        print(f"[az] {exc}")
        return 1
    return _start(name, command, cwd, marker, log, env)


def _game_process_pid() -> int | None:
    try:
        return int((PRIVATE / "state" / "game.pid").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _stop_private_sidecar(filename: str, marker: str) -> None:
    pid_file = PRIVATE / "state" / filename
    try:
        pid = int(pid_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    command = _process_command(pid)
    if command and marker.casefold() in command.casefold():
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=WINDOWS_HIDDEN,
        )
    pid_file.unlink(missing_ok=True)


def _private_client_running() -> bool:
    pid = _game_process_pid()
    if pid is None:
        return False
    command = _process_command(pid)
    exe = str((PRIVATE / "runtime" / "Bin64" / "NewWorld.exe")).casefold()
    return bool(command and exe in command.casefold())


def _game_action(action: str, args: list[str]) -> int:
    record = _read_record("game")
    supervisor_up = _running("game", record)
    client_up = _private_client_running()
    if action == "status":
        if supervisor_up or client_up:
            print(f"game: running (client pid {_game_process_pid() or 'unknown'})")
        else:
            print("game: stopped")
        return 0
    if action == "stop":
        _stop("game")
        _stop_private_sidecar("eos.pid", "frida-eos-stub.py")
        pid = _game_process_pid()
        if pid and _private_client_running():
            subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=WINDOWS_HIDDEN,
            )
            print(f"[az] private client stopped (pid {pid})")
        (PRIVATE / "state" / "game.pid").unlink(missing_ok=True)
        return 0
    if action == "restart":
        _game_action("stop", [])
        time.sleep(1)
        action = "start"
    if action != "start":
        print("usage: python az.py game [start|stop|restart|status] [--install <path>]")
        return 2
    if supervisor_up or client_up:
        print("[az] private client already running; use `python az.py game restart`")
        return 0
    if _mode(["status"]):
        print("[az] private host routing is not active; switch it before launching the private client")
        return 2
    if not (ROOT / ".azoth" / "venv" / "Scripts" / "python.exe").is_file():
        print("[az] local tools are not installed; run `python az.py setup` first")
        return 2
    launcher = ROOT / "services" / "launcher" / "src" / "Start-NwPrivate.ps1"
    command = [*PS, "-File", str(launcher), "-Watch"]
    if args:
        if len(args) != 2 or args[0] != "--install":
            print("usage: python az.py game [start|stop|restart|status] [--install <path>]")
            return 2
        command.extend(["-InstallRoot", args[1]])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return _start(
        "game", command, ROOT,
        "Start-NwPrivate.ps1",
        LOGS / f"game-{stamp}.log",
        local_env(),
    )


def _status() -> int:
    for name in ("caddy", "gateway", "world", "game"):
        if name == "game":
            _game_action("status", [])
        else:
            _service_action(name, "status")
    return 0


def _tests(service: str) -> int:
    python = app_python()
    if service == "gateway":
        tests = ROOT / "services" / "gateway" / "tests" / "test_gateway.py"
        return subprocess.call([python, str(tests)], cwd=ROOT, env=local_env())
    if service == "world":
        tests = ROOT / "services" / "world" / "tests"
        result = subprocess.call(
            [python, "-m", "unittest", "discover", "-s", str(tests)],
            cwd=ROOT,
            env=local_env(),
        )
        return result
    return 2


def _mode(args: list[str]) -> int:
    action = args[0] if args else "status"
    return subprocess.call([*PS, "-File", str(ROOT / "deploy" / "switch-mode.ps1"), action], cwd=ROOT)


def _run_script(args: list[str]) -> int:
    if not args:
        print("usage: python az.py run <script-name> [args]")
        return 2
    script = SCRIPTS / args[0]
    if not script.is_file():
        print(f"script not found: {script}")
        return 2
    return subprocess.call([app_python(), str(script), *args[1:]], cwd=ROOT, env=local_env())


def _run_probe(args: list[str]) -> int:
    if not args:
        print("usage: python az.py probe <probe-name> [args] | python az.py probe list")
        return 2
    if args[0] == "list":
        probe_dir = ROOT / "reverse" / "probes" / "client"
        for path in sorted(probe_dir.glob("frida-*.py")):
            try:
                description = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
            except (OSError, SyntaxError):
                description = None
            summary = description.splitlines()[0] if description else ""
            print(f"{path.stem:34} {summary}")
        return 0
    name = args[0] if args[0].endswith(".py") else f"{args[0]}.py"
    if Path(name).name != name:
        print("probe name must be a filename under reverse/probes/client")
        return 2
    probe = ROOT / "reverse" / "probes" / "client" / name
    if not probe.is_file():
        print(f"probe not found: {probe}")
        return 2
    return subprocess.call([app_python(), str(probe), *args[1:]], cwd=ROOT, env=local_env())


def _reverse_tool(args: list[str]) -> int:
    commands = {
        "decompile": ROOT / "reverse" / "tools" / "decomp.py",
        "corpus": ROOT / "reverse" / "tools" / "corpus.py",
        "campaign": ROOT / "reverse" / "tools" / "campaign.py",
        "pe": ROOT / "reverse" / "tools" / "peutil.py",
        "strings": ROOT / "reverse" / "tools" / "strings.py",
        "xref": ROOT / "reverse" / "tools" / "xrefmap.py",
        "naming": ROOT / "reverse" / "tools" / "namer.py",
        "types": ROOT / "reverse" / "tools" / "rtti.py",
        "pak-index": ROOT / "reverse" / "tools" / "pakindex.py",
        "pak-read": ROOT / "reverse" / "tools" / "pakread.py",
        "ingest-log": ROOT / "research" / "tools" / "capture" / "nw_capture.py",
    }
    descriptions = {
        "decompile": "decompile a selected function or caller chain",
        "corpus": "account for and decompile every function range in one client build",
        "campaign": "run the incremental phase-scoped decompilation campaign",
        "pe": "inspect executable sections, function bounds, and callers",
        "strings": "search strings from the installed client executable",
        "xref": "build or query the cached native cross-reference map",
        "naming": "generate evidence-linked function name candidates for review",
        "types": "inspect RTTI and native type metadata",
        "pak-index": "index game package directories",
        "pak-read": "inspect or decode entries from a game package",
        "ingest-log": "turn an existing Game.log into a structured session",
    }
    if not args or args[0] in {"list", "--help", "-h"}:
        print("usage: python az.py re <workflow> [args]")
        for name, description in descriptions.items():
            print(f"  {name:12} {description}")
        return 0
    name, *rest = args
    script = commands.get(name)
    if script is None:
        print(f"unknown RE workflow: {name}")
        print("run `python az.py re list` to see available workflows")
        return 2
    return subprocess.call([app_python(), str(script), *rest], cwd=ROOT, env=local_env())


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    head, *rest = argv
    if head == "migrate":
        if rest:
            print("usage: python az.py migrate")
            return 2
        return _migrate_appdata()
    if head == "setup":
        return subprocess.call(
            [sys.executable, str(SCRIPTS / "bootstrap.py"), *rest],
            cwd=ROOT,
            env=local_env(),
        )
    if head == "status":
        return _status()
    if head == "stop":
        _game_action("stop", [])
        for name in ("world", "gateway", "caddy"):
            _stop(name)
        return 0
    if head in {"gateway", "world", "caddy"}:
        action = rest[0] if rest else "start"
        if action == "test":
            return _tests(head)
        return _service_action(head, action)
    if head == "dev":
        action = rest[0] if rest else "start"
        if action == "status":
            for name in ("gateway", "world", "caddy"):
                _service_action(name, "status")
            return 0
        if action == "stop":
            for name in ("caddy", "world", "gateway"):
                _stop(name)
            return 0
        if action not in {"start", "restart"}:
            print("usage: python az.py dev [start|stop|restart|status]")
            return 2
        if action == "restart":
            for name in ("caddy", "world", "gateway"):
                _stop(name)
        started = []
        for name in ("gateway", "world", "caddy"):
            if not _running(name):
                started.append(name)
            code = _service_action(name, "start")
            if code:
                for started_name in reversed(started):
                    _stop(started_name)
                return code
        return 0
    if head == "game":
        action = rest[0] if rest and not rest[0].startswith("--") else "start"
        extra = rest[1:] if rest and not rest[0].startswith("--") else rest
        return _game_action(action, extra)
    if head == "mode":
        return _mode(rest)
    if head == "doc":
        return subprocess.call([app_python(), str(SCRIPTS / "gen_openapi.py")], cwd=ROOT, env=local_env())
    if head == "shape":
        return subprocess.call(
            [app_python(), str(SCRIPTS / "try-world-shape.py"), *rest],
            cwd=ROOT,
            env=local_env(),
        )
    if head == "run":
        return _run_script(rest)
    if head == "probe":
        return _run_probe(rest)
    if head == "re":
        return _reverse_tool(rest)
    if head in {"click", "post", "shot", "key"}:
        script = {"click": "click-window.py", "post": "post-input.py", "shot": "shot.py", "key": "send-input.py"}[head]
        return subprocess.call([app_python(), str(SCRIPTS / script), *rest], cwd=ROOT, env=local_env())
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
