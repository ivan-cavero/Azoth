"""Gateway, world, Caddy, and the static site."""

from __future__ import annotations

import os
import subprocess

from lab.catalog import resolve_script
from lab.env import app_python, local_env
from lab.paths import LOGS, ROOT
from lab.procs import read_record, running, start, stop


def refresh_live() -> int:
    script = ROOT / "platform" / "web" / "scripts" / "update_live.py"
    if not script.exists():
        return 0
    try:
        return subprocess.call(
            [app_python(), str(script)],
            cwd=ROOT,
            env=local_env(),
            stdout=subprocess.DEVNULL,
        )
    except OSError:
        return 0


def service_command(name: str) -> tuple[list[str], object, str, object, dict[str, str] | None]:
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
            raise FileNotFoundError("Caddy is missing; run `python ef.py setup` first")
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
    if name == "web":
        dist = ROOT / "platform" / "web" / "dist"
        if not (dist / "index.html").is_file():
            raise FileNotFoundError(
                "platform/web/dist is missing; run `npm run build` in platform/web/"
            )
        port = os.environ.get("AZOTH_WEB_PORT", "8090")
        return (
            [python, "-u", "-m", "http.server", port, "--bind", "127.0.0.1"],
            dist,
            f"http.server {port}",
            LOGS / "web.log",
            None,
        )
    raise ValueError(name)


def service_action(name: str, action: str) -> int:
    if action == "status":
        record = read_record(name)
        if running(name, record):
            print(f"{name}: running (pid {record['pid']}, log {record['log']})")
        else:
            print(f"{name}: stopped")
        return 0
    if action == "stop":
        stop(name)
        return 0
    if action == "restart":
        stop(name)
    if action != "start" and action != "restart":
        print(f"usage: python ef.py {name} [start|stop|restart|status|test]")
        return 2
    try:
        command, cwd, marker, log, env = service_command(name)
    except OSError as exc:
        print(f"[ef] {exc}")
        return 1
    return start(name, command, cwd, marker, log, env)


def run_tests(service: str) -> int:
    tests = ROOT / "services" / service / "tests"
    if not tests.is_dir():
        return 2
    return subprocess.call(
        [app_python(), "-m", "unittest", "discover", "-s", str(tests)],
        cwd=ROOT,
        env=local_env(),
    )


def dev(action: str) -> int:
    if action == "status":
        for name in ("gateway", "world", "caddy"):
            service_action(name, "status")
        return 0
    if action == "stop":
        for name in ("caddy", "world", "gateway"):
            stop(name)
        refresh_live()
        return 0
    if action not in {"start", "restart"}:
        print("usage: python ef.py dev [start|stop|restart|status]")
        return 2
    if action == "restart":
        for name in ("caddy", "world", "gateway"):
            stop(name)
    started = []
    for name in ("gateway", "world", "caddy"):
        if not running(name):
            started.append(name)
        code = service_action(name, "start")
        if code:
            for started_name in reversed(started):
                stop(started_name)
            refresh_live()
            return code
    refresh_live()
    return 0


def call_script(stem: str, args: list[str]) -> int:
    script = resolve_script(stem)
    if script is None:
        print(f"script not found: {stem}")
        return 2
    return subprocess.call([app_python(), str(script), *args], cwd=ROOT, env=local_env())
