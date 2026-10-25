"""Script, probe, and reverse-engineering dispatch."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from lab.catalog import resolve_script, reverse_catalog, script_catalog
from lab.env import app_python, local_env
from lab.paths import ROOT


def cargo(_args: list[str]) -> int:
    print("No Rust server in this checkout.")
    print("Read research/atlas/meanings.md and docs/PLAN.md.")
    print("A crate comes back only after that file names the fields it would send.")
    if _args:
        print("ignored:", " ".join(_args))
    return 2


def run_script(args: list[str]) -> int:
    if not args or args[0] in {"list", "--help", "-h"}:
        print("usage: python ef.py run <script-stem|path> [args]")
        print("catalog: scripts/catalog.json  (by kind under scripts/<kind>/)")
        by_kind: dict[str, list[str]] = {}
        for stem, meta in sorted(script_catalog().items()):
            by_kind.setdefault(str(meta.get("kind", "?")), []).append(stem)
        for kind in sorted(by_kind):
            print(f"  [{kind}]")
            for stem in by_kind[kind]:
                print(f"    {stem}")
        return 0
    script = resolve_script(args[0])
    if script is None:
        print(f"script not found: {args[0]} (try `python ef.py run list`)")
        return 2
    return subprocess.call([app_python(), str(script), *args[1:]], cwd=ROOT, env=local_env())


def run_probe(args: list[str]) -> int:
    if not args:
        print("usage: python ef.py probe <probe-name> [args] | python ef.py probe list")
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


def reverse_tool(args: list[str]) -> int:
    tools = ROOT / "reverse" / "tools"
    workflows = reverse_catalog()
    commands: dict[str, Path] = {
        name: tools / meta["path"]
        for name, meta in workflows.items()
        if (tools / meta["path"]).is_file()
    }
    commands["ingest-log"] = ROOT / "research" / "tools" / "capture" / "nw_capture.py"
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
        print("usage: python ef.py re <workflow> [args]")
        for name in sorted(commands):
            description = descriptions.get(name, workflows.get(name, {}).get("kind", ""))
            print(f"  {name:12} {description}")
        return 0
    name, *rest = args
    script = commands.get(name)
    if script is None:
        print(f"unknown RE workflow: {name}")
        print("run `python ef.py re list` to see available workflows")
        return 2
    return subprocess.call([app_python(), str(script), *rest], cwd=ROOT, env=local_env())
