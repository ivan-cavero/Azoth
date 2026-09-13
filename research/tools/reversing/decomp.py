#!/usr/bin/env python3
"""Decompile specific functions of NewWorld.exe with Ghidra headless.

Why this exists: reading the client's own code is the only way to settle questions
the strings can't (which JSON key is read, what predicate rejects a world, what a
cached error code means). Doing that by hand is a Ghidra GUI session; this makes it
one command and caches the project so repeat runs take seconds.

Pipeline:
  1. resolve each target to an exact function range (`.pdata` via peutil, or a
     symbol name from research/derived/symbols.json)
  2. compile ghidra/DecompileTargets.java against the Ghidra jars (once)
  3. run Ghidra headless: -import the exe on first use, then -process (cached)
  4. append the decompiled C to the output file

Targets are chosen by address, by symbol name, or by walking up from a leaf:
  --target 0x144f54d63              # the code that reads a property
  --symbol worldtype_mapper         # a known landmark
  --callers-of 0x1417c40a0          # every function that calls it

Usage:
  python research/tools/reversing/decomp.py --symbol worldtype_mapper
  python research/tools/reversing/decomp.py --target 0x144ad6e70 --out big.txt
  python research/tools/reversing/decomp.py --callers-of 0x1417c40a0
  python research/tools/reversing/decomp.py --selftest
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402
from peutil import PEx  # noqa: E402

HERE = Path(__file__).resolve().parent
GHIDRA_DIR = HERE / "ghidra"
SYMBOLS_FILE = HERE.parents[1] / "derived" / "symbols.json"
JAVA_SRC = GHIDRA_DIR / "DecompileTargets.java"
CLASS_NAME = "DecompileTargets.class"

# Where Ghidra lives / where its project goes. Overridable by env so another
# machine (or a different Ghidra build) works without editing this file.
GHIDRA_HOME = Path(
    os.environ.get("GHIDRA_HOME", r"C:\Users\ivang\tools\ghidra_12.1.3_PUBLIC")
)
WORK = Path(os.environ.get("AZOTH_DECOMP_WORK", r"C:\Users\ivang\tools"))
PROJECT_DIR = WORK / "ghproj"
PROJECT_NAME = "azoth"
PROGRAM_NAME = "NewWorld.exe"


def ghidra_paths() -> dict:
    return {
        "headless": GHIDRA_HOME / "support" / "analyzeHeadless.bat",
        "jdk": Path(
            os.environ.get(
                "JAVA_HOME",
                r"C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot",
            )
        ),
    }


def check_install() -> list[str]:
    """Return a list of human-readable problems (empty = ready)."""
    problems = []
    g = ghidra_paths()
    if not g["headless"].is_file():
        problems.append(f"Ghidra headless not found: {g['headless']} (set GHIDRA_HOME)")
    if not (g["jdk"] / "bin" / "javac.exe").is_file():
        problems.append(f"JDK javac not found under {g['jdk']} (set JAVA_HOME)")
    if not JAVA_SRC.is_file():
        problems.append(f"script source missing: {JAVA_SRC}")
    return problems


def classpath() -> str:
    """Every Ghidra jar, for javac against GhidraScript/DecompInterface."""
    patterns = (
        "Ghidra/Framework/*/lib/*.jar",
        "Ghidra/Features/*/lib/*.jar",
        "Ghidra/Processors/*/lib/*.jar",
        "Ghidra/Test/*/lib/*.jar",
    )
    jars: list[str] = []
    for pat in patterns:
        jars += glob.glob(str(GHIDRA_HOME / pat))
    return ";".join(sorted({os.path.normpath(j) for j in jars}))


def ensure_compiled(force: bool = False) -> Path:
    """Compile the helper into a Ghidra script dir; return the script dir."""
    script_dir = WORK / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    target = script_dir / CLASS_NAME
    if (
        target.is_file()
        and not force
        and target.stat().st_mtime >= JAVA_SRC.stat().st_mtime
    ):
        return script_dir
    g = ghidra_paths()
    javac = g["jdk"] / "bin" / "javac.exe"
    out_dir = WORK / "classes"
    out_dir.mkdir(parents=True, exist_ok=True)
    cp = classpath()
    if not cp:
        raise RuntimeError(f"no Ghidra jars under {GHIDRA_HOME}")
    res = subprocess.run(
        [str(javac), "-nowarn", "-cp", cp, "-d", str(out_dir), str(JAVA_SRC)],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"javac failed:\n{res.stdout}\n{res.stderr}")
    produced = out_dir / CLASS_NAME
    if not produced.is_file():
        raise RuntimeError(f"javac produced no {CLASS_NAME}")
    shutil.copy2(produced, target)
    return script_dir


def load_symbols() -> dict:
    if not SYMBOLS_FILE.is_file():
        return {}
    try:
        return json.loads(SYMBOLS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: ignoring unreadable {SYMBOLS_FILE}: {exc}", file=sys.stderr)
        return {}


def resolve_targets(args: argparse.Namespace, pex: PEx) -> list[tuple[str, int, int]]:
    """Return [(label, start, end)] for every requested target."""
    out: list[tuple[str, int, int]] = []
    symbols = load_symbols()

    def add_range(label: str, start: int, end: int | None = None) -> None:
        if end is None:
            r = pex.func_at(start)
            if r is None:
                raise SystemExit(
                    f"{label}: {hex(start)} is not inside any .pdata function"
                )
            start, end = r
        out.append((label, start, end))

    for raw in args.target or []:
        va = int(raw, 16)
        add_range(f"target:{raw}", va)
    for name in args.symbol or []:
        sym = symbols.get(name)
        if not sym:
            known = ", ".join(sorted(symbols)) or "(none)"
            raise SystemExit(f"unknown symbol {name!r}; known: {known}")
        add_range(f"symbol:{name}", int(sym["va"], 16))
    for raw in args.callers_of or []:
        va = int(raw, 16)
        for i, (s, e) in enumerate(pex.caller_funcs(va)):
            out.append((f"caller{i}:{hex(s)}", s, e))
    if args.range:
        s, e = (int(x, 16) for x in args.range.split("-"))
        out.append((f"range:{args.range}", s, e))
    if not out:
        raise SystemExit(
            "no targets: pass --target / --symbol / --callers-of / --range"
        )
    return out


def run_ghidra(
    ranges: list[tuple[str, int, int]], out_file: Path, timeout: int
) -> None:
    script_dir = ensure_compiled()
    g = ghidra_paths()
    exe = default_paths()["exe"]
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    args = [
        str(g["headless"]),
        str(PROJECT_DIR),
        PROJECT_NAME,
    ]
    # First run imports (slow, one-off); later runs reuse the cached program.
    imported = (PROJECT_DIR / f"{PROJECT_NAME}.rep").is_dir()
    if imported:
        args += ["-process", PROGRAM_NAME]
    else:
        args += ["-import", str(exe)]
    args += [
        "-noanalysis",
        "-scriptPath",
        str(script_dir),
        "-postScript",
        CLASS_NAME,
    ]
    args += [f"{s:x}-{e:x}" for _, s, e in ranges]

    env = dict(os.environ)
    env["JAVA_HOME"] = str(g["jdk"])
    env["MAXMEM"] = env.get("AZOTH_DECOMP_MAXMEM", "12G")
    env["DECOMP_OUT"] = str(out_file)
    # cmd.exe mangles (x86) paths in .bat args unless the short name is used.
    print(
        f"[decomp] {'import+process' if not imported else 'process'} "
        f"{len(ranges)} range(s) -> {out_file}"
    )
    res = subprocess.run(
        ["cmd.exe", "/c", str(args[0]), *args[1:]],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    log = (res.stdout or "") + (res.stderr or "")
    (WORK / "ghidra-last.log").write_text(log, encoding="utf-8", errors="replace")
    if "SCRIPT ERROR" in log or "Exception" in log and "ERROR" in log:
        tail = "\n".join(log.strip().splitlines()[-15:])
        raise SystemExit(
            f"Ghidra reported an error (see {WORK / 'ghidra-last.log'}):\n{tail}"
        )


def selftest(pex: PEx) -> int:
    """Prove the toolkit works end to end, using a tiny known function."""
    problems = check_install()
    if problems:
        for p in problems:
            print("MISSING " + p)
        return 1
    print("install: OK")
    script_dir = ensure_compiled()
    print(f"compiled: {script_dir / CLASS_NAME}")
    out = WORK / "selftest_decomp.txt"
    if out.exists():
        out.unlink()
    # 251-byte function: the smallest of the WorldType mapper's callers.
    r = pex.func_at(0x146474D48)
    if not r:
        print("selftest: FAILED (no .pdata range at 0x146474d48)")
        return 1
    run_ghidra([("selftest", r[0], r[1])], out, timeout=1800)
    text = out.read_text(encoding="utf-8", errors="replace")
    ok = "FUNC " in text and "DECOMP-FAIL" not in text and "ERR " not in text
    print(f"output: {len(text)} bytes")
    print("selftest:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Decompile functions of NewWorld.exe")
    ap.add_argument("--target", action="append", help="hex VA inside a function")
    ap.add_argument("--symbol", action="append", help="name from derived/symbols.json")
    ap.add_argument(
        "--callers-of", action="append", help="hex VA; decompile its callers"
    )
    ap.add_argument("--range", help="hex start-end, bypassing .pdata lookup")
    ap.add_argument(
        "--out", help="output file (default derived/decomp/<first target>.c)"
    )
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--recompile", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    pex = PEx(default_paths()["exe"])
    if args.selftest:
        return selftest(pex)
    problems = check_install()
    if problems:
        for p in problems:
            print("MISSING " + p, file=sys.stderr)
        return 1
    if args.recompile:
        ensure_compiled(force=True)

    ranges = resolve_targets(args, pex)
    if args.out:
        out_file = Path(args.out)
    else:
        first = ranges[0]
        out_file = (
            HERE.parents[1] / "derived" / "decomp" / f"{first[1]:x}-{first[2]:x}.c"
        )
    run_ghidra(ranges, out_file, args.timeout)
    text = out_file.read_text(encoding="utf-8", errors="replace")
    print(f"[decomp] wrote {len(text)} bytes to {out_file}")
    for label, s, e in ranges:
        print(f"  {label}  {hex(s)}-{hex(e)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
