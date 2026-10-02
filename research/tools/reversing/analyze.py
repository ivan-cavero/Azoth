#!/usr/bin/env python3
"""Import the client into a second Ghidra project WITH auto-analysis.

Why this exists: the layer-1 corpus (`corpus.py`) is imported with
`-noanalysis` on purpose, so it is fast and small, but it has no strings, no
symbols and no data references. That makes string-anchored navigation and
"what references this address" impossible, which blocks any question about a
function reached through a vtable — for example the PAK method-15 codec.

This project is the complement: the same exe, fully analyzed, in a separate
directory so the corpus project is never touched. The corpus stays valid; this
one answers the questions the corpus cannot.

The decompiler-based analyzers are disabled first (`DisableSlowAnalyzers.java`)
because they dominate runtime and add nothing for navigation by strings,
references and data xrefs.

Usage:
  python research/tools/reversing/analyze.py            # launch in background
  python research/tools/reversing/analyze.py --status   # is it still running?
  python research/tools/reversing/analyze.py --wait     # block until it exits
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402
from decomp import (  # noqa: E402
    WORK,
    check_install,
    classpath,
    cmd_safe_args,
    ensure_compiled,
    ghidra_paths,
    pid_alive,
)

HERE = Path(__file__).resolve().parent
JAVA_SRC = HERE / "ghidra" / "DisableSlowAnalyzers.java"
CLASS = "DisableSlowAnalyzers.class"

# A separate project, never the corpus one.
PROJECT_DIR = WORK / "ghproj-analyzed"
PROJECT_NAME = "azoth-analyzed"
PROGRAM_NAME = "NewWorld.exe"
PID_FILE = WORK / "analyze.pid"
LOG_FILE = WORK / "analyze.log"

# Hard bound on analysis time per file, so a pathological binary cannot run
# forever. The analyzer set is already reduced; this is the backstop.
ANALYSIS_TIMEOUT_S = 5400


def compile_prescript() -> Path:
    """Compile the analyzer preScript beside the existing helper classes."""
    script_dir = ensure_compiled()
    out_dir = WORK / "classes"
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = out_dir / CLASS
    fresh = produced.is_file() and produced.stat().st_mtime >= JAVA_SRC.stat().st_mtime
    if not fresh:
        javac = ghidra_paths()["jdk"] / "bin" / "javac.exe"
        res = subprocess.run(
            [str(javac), "-nowarn", "-cp", classpath(), "-d", str(out_dir), str(JAVA_SRC)],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise SystemExit(f"javac failed:\n{res.stdout}\n{res.stderr}")
    if not produced.is_file():
        raise SystemExit(f"javac produced no {CLASS}")
    for extra in out_dir.glob("DisableSlowAnalyzers*.class"):
        shutil.copy2(extra, script_dir / extra.name)
    if not (script_dir / CLASS).is_file():
        raise SystemExit(f"missing {script_dir / CLASS}")
    return script_dir


def running() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def launch() -> int:
    problems = check_install()
    if problems:
        raise SystemExit("MISSING " + "; ".join(problems))
    exe = default_paths()["exe"]
    if not exe.is_file():
        raise SystemExit(f"[analyze] exe missing: {exe}")
    existing = running()
    if existing:
        print(f"[analyze] already running pid={existing}")
        return 0
    if (PROJECT_DIR / f"{PROJECT_NAME}.rep").is_dir():
        print(f"[analyze] project already exists: {PROJECT_DIR}")
        print("[analyze] delete it to re-analyze; refusing to overwrite.")
        return 1
    script_dir = compile_prescript()
    g = ghidra_paths()
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        str(g["headless"]),
        str(PROJECT_DIR),
        PROJECT_NAME,
        "-import",
        str(exe),
        "-scriptPath",
        str(script_dir),
        "-preScript",
        CLASS,
        "-analysisTimeoutPerFile",
        str(ANALYSIS_TIMEOUT_S),
    ]
    env = dict(os.environ)
    env["JAVA_HOME"] = str(g["jdk"])
    # Ghidra 12.1.4's analyzeHeadless.bat reads GHIDRA_MAXMEM /
    # GHIDRA_HEADLESS_MAXMEM and defaults to a hard 2G. It does NOT read
    # MAXMEM -- that name is only a positional argument of launch.bat, so
    # setting it here had no effect and every run silently used 2G. Verified
    # on a live JVM: "-Xmx2G" was on the command line despite MAXMEM=12G.
    # Under 2G the analysis spends its time in CodeUnitDB.getBytes re-reading
    # instruction bytes while GC thrashes, which on this exe means hours in the
    # early analyzers. Keep GHIDRA_MAXMEM and GHIDRA_HEADLESS_MAXMEM in sync.
    heap = env.get("AZOTH_ANALYZE_MAXMEM", "16G")
    env["GHIDRA_MAXMEM"] = heap
    env["GHIDRA_HEADLESS_MAXMEM"] = heap
    log = LOG_FILE.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        ["cmd.exe", "/c", *cmd_safe_args([str(args[0]), *args[1:]])],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    print(f"[analyze] pid={proc.pid}")
    print(f"[analyze] project {PROJECT_DIR}")
    print(f"[analyze] log {LOG_FILE}")
    print(f"[analyze] timeout {ANALYSIS_TIMEOUT_S}s")
    return 0


def status() -> int:
    pid = running()
    rep = PROJECT_DIR / f"{PROJECT_NAME}.rep"
    print(f"[analyze] pid={pid if pid else 'not running'}")
    print(f"[analyze] project={'present' if rep.is_dir() else 'absent'} {PROJECT_DIR}")
    if LOG_FILE.is_file():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"[analyze] log {len(lines)} lines; last 12:")
        for line in lines[-12:]:
            print("   ", line[:160])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze NewWorld.exe in a second Ghidra project")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--wait", action="store_true", help="block until the Ghidra process exits")
    args = ap.parse_args()
    if args.status:
        return status()
    code = launch()
    if code != 0 or not args.wait:
        return code
    pid = running()
    while pid and pid_alive(pid):
        time.sleep(10)
    print("[analyze] exited")
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
