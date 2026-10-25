"""Argument dispatch. ef.py only calls main."""

from __future__ import annotations

import sys

from lab.catalog import resolve_script
from lab.env import local_env
from lab.game import game_action, status
from lab.host import mode
from lab.migrate import migrate_appdata
from lab.paths import ROOT
from lab.procs import stop
from lab.services import call_script, dev, refresh_live, run_tests, service_action
from lab.tools import cargo, reverse_tool, run_probe, run_script


def main(usage: str | None = None) -> int:
    argv = sys.argv[1:]
    if not argv:
        print(usage or "usage: python ef.py <command>")
        return 0
    head, *rest = argv
    if head == "migrate":
        if rest:
            print("usage: python ef.py migrate")
            return 2
        return migrate_appdata()
    if head == "setup":
        bootstrap = resolve_script("bootstrap")
        assert bootstrap is not None
        return subprocess_call(bootstrap, rest)
    if head == "doctor":
        doctor = resolve_script("doctor")
        assert doctor is not None
        return subprocess_call(doctor, rest)
    if head == "test":
        if rest[:2] == ["e2e", "entry"]:
            stub = resolve_script("e2e-entry-stub")
            assert stub is not None
            return subprocess_call(stub, rest[2:])
        print("usage: python ef.py test e2e entry")
        return 2
    if head == "status":
        return status()
    if head == "stop":
        game_action("stop", [])
        for name in ("world", "gateway", "caddy", "web"):
            stop(name)
        refresh_live()
        return 0
    if head in {"gateway", "world", "caddy", "web"}:
        action = rest[0] if rest else "start"
        if action == "test":
            return run_tests(head)
        code = service_action(head, action)
        if head == "web" and action in {"start", "stop", "restart"}:
            refresh_live()
        return code
    if head == "dev":
        action = rest[0] if rest else "start"
        return dev(action)
    if head == "game":
        action = rest[0] if rest and not rest[0].startswith("--") else "start"
        extra = rest[1:] if rest and not rest[0].startswith("--") else rest
        return game_action(action, extra)
    if head == "mode":
        return mode(rest)
    if head == "doc":
        return call_script("gen_openapi", [])
    if head == "shape":
        return call_script("try-world-shape", rest)
    if head == "run":
        return run_script(rest)
    if head == "probe":
        return run_probe(rest)
    if head == "re":
        return reverse_tool(rest)
    if head == "cargo":
        return cargo(rest)
    if head in {"click", "post", "shot", "key"}:
        stem = {
            "click": "click-window",
            "post": "post-input",
            "shot": "shot",
            "key": "send-input",
        }[head]
        return call_script(stem, rest)
    print(usage or "usage: python ef.py <command>")
    return 2


def subprocess_call(script, args: list[str]) -> int:
    import subprocess

    return subprocess.call(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        env=local_env(),
    )