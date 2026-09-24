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
  --serve                           # one long-lived Ghidra; later calls enqueue

One-shot headless passes -readOnly so a query does not rewrite the ~480MB
project database. `--serve` keeps that JVM open: the first open is still
slow, every later function is a file drop in the queue (~seconds).

Usage:
  python research/tools/reversing/decomp.py --serve
  python research/tools/reversing/decomp.py --symbol worldtype_mapper
  python research/tools/reversing/decomp.py --target 0x144ad6e70 --out big.txt
  python research/tools/reversing/decomp.py --callers-of 0x1417c40a0
  python research/tools/reversing/decomp.py --stop
  python research/tools/reversing/decomp.py --selftest
"""

from __future__ import annotations

import argparse
import bisect
import glob
import json
import os
import shutil
import subprocess
import sys
import time
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
QUEUE = WORK / "decomp-queue"
PID_FILE = QUEUE / "server.pid"
READY_FILE = QUEUE / "ready"
STOP_FILE = QUEUE / "stop"
REQ_FILE = QUEUE / "request.txt"
DONE_FILE = QUEUE / "request.done"
SERVER_LOG = WORK / "decomp-server.log"


def resolve_jdk() -> Path:
    """JDK 21 that actually exists. JAVA_HOME wins when its javac is real.

    The old hardcoded 21.0.11 path is not installed on this machine; a missing
    fallback made headless fail closed instead of using jdk-21.* under Adoptium.
    """
    env = os.environ.get("JAVA_HOME")
    if env and (Path(env) / "bin" / "javac.exe").is_file():
        return Path(env)
    adoptium = Path(r"C:\Program Files\Eclipse Adoptium")
    if adoptium.is_dir():
        found = sorted(
            (
                p
                for p in adoptium.glob("jdk-21*")
                if (p / "bin" / "javac.exe").is_file()
            ),
            key=lambda p: p.name,
            reverse=True,
        )
        if found:
            return found[0]
    return Path(env or str(adoptium / "jdk-21"))


def ghidra_paths() -> dict:
    return {
        "headless": GHIDRA_HOME / "support" / "analyzeHeadless.bat",
        "jdk": resolve_jdk(),
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


def pdata_overlap(pex: PEx, start: int, end: int) -> list[tuple[int, int]]:
    """`.pdata` functions that overlap [start, end)."""
    ranges = pex.ranges
    i = bisect.bisect_right(pex._starts, start) - 1
    if i < 0:
        i = 0
    elif ranges[i][1] <= start:
        i += 1
    out: list[tuple[int, int]] = []
    while i < len(ranges) and ranges[i][0] < end:
        if ranges[i][1] > start:
            out.append(ranges[i])
        i += 1
    return out


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
        # A page-aligned guess (146b6e000-146b6f200) is not a function entry.
        # Ghidra then emits a 1-byte halt_baddata stub and we paid a full
        # headless run for nothing. Snap onto the real .pdata functions.
        hit = pdata_overlap(pex, s, e)
        if not hit:
            out.append((f"range:{args.range}", s, e))
        elif len(hit) > 12:
            one = pex.func_at(s) or hit[0]
            print(
                f"[decomp] range {s:x}-{e:x} covers {len(hit)} functions; "
                f"using {one[0]:x}-{one[1]:x}"
            )
            out.append((f"range:{one[0]:x}-{one[1]:x}", one[0], one[1]))
        else:
            if hit != [(s, e)]:
                print(
                    f"[decomp] snap {s:x}-{e:x} -> "
                    + ", ".join(f"{a:x}-{b:x}" for a, b in hit)
                )
            for a, b in hit:
                out.append((f"range:{a:x}-{b:x}", a, b))
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
    args += ["-noanalysis"]
    # -process rewrites the ~480MB project db on exit. -readOnly discards
    # the script's function edits instead. Do NOT pass it on a first -import:
    # that mode would throw the import away.
    if imported:
        args.append("-readOnly")
    args += [
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


def pid_alive(pid: int) -> bool:
    """True if pid is a live process.

    os.kill(pid, 0) raises WinError 87 for any pid except our own, so a
    running decomp server looked dead and the client started a second
    Ghidra that could not lock the project.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def server_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def headless_cmd(script_dir: Path) -> tuple[list[str], dict]:
    """analyzeHeadless argv + env. Caller appends -postScript args."""
    g = ghidra_paths()
    args = [
        str(g["headless"]),
        str(PROJECT_DIR),
        PROJECT_NAME,
        "-process",
        PROGRAM_NAME,
        "-noanalysis",
        "-readOnly",
        "-scriptPath",
        str(script_dir),
        "-postScript",
        CLASS_NAME,
    ]
    env = dict(os.environ)
    env["JAVA_HOME"] = str(g["jdk"])
    env["MAXMEM"] = env.get("AZOTH_DECOMP_MAXMEM", "12G")
    return args, env


def serve() -> int:
    """One JVM, project stays open, jobs arrive as files in the queue."""
    problems = check_install()
    if problems:
        for p in problems:
            print("MISSING " + p, file=sys.stderr)
        return 1
    existing = server_pid()
    if existing:
        state = "ready" if READY_FILE.is_file() else "still opening the project"
        print(f"[decomp] server already up pid={existing} ({state})")
        return 0
    if not (PROJECT_DIR / f"{PROJECT_NAME}.rep").is_dir():
        raise SystemExit(
            "[decomp] no cached project — run one --target first so --serve "
            "can -process instead of re-importing"
        )
    script_dir = ensure_compiled()
    QUEUE.mkdir(parents=True, exist_ok=True)
    for stale in (STOP_FILE, READY_FILE, REQ_FILE, DONE_FILE, QUEUE / "request.txt.busy"):
        if stale.exists():
            stale.unlink()
    args, env = headless_cmd(script_dir)
    env["DECOMP_SERVE"] = "1"
    env["DECOMP_QUEUE"] = str(QUEUE)
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = SERVER_LOG.open("w", encoding="utf-8")
    print(f"[decomp] server starting; log {SERVER_LOG}")
    proc = subprocess.Popen(
        ["cmd.exe", "/c", str(args[0]), *args[1:]],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    print(f"[decomp] server pid={proc.pid}", flush=True)
    rc = proc.wait()
    print(f"[decomp] server exited {rc}")
    return rc


def wait_ready(timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if READY_FILE.is_file() and server_pid():
            return
        if server_pid() is None:
            tail = ""
            if SERVER_LOG.is_file():
                lines = SERVER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = "\n".join(lines[-12:])
            raise SystemExit(f"decomp server exited before ready\n{tail}")
        time.sleep(0.5)
    raise SystemExit(f"decomp server not ready after {timeout}s (see {SERVER_LOG})")


def enqueue(ranges: list[tuple[str, int, int]], out_file: Path, timeout: int) -> None:
    deadline = time.time() + timeout
    busy = QUEUE / "request.txt.busy"
    while REQ_FILE.exists() or busy.exists():
        if time.time() > deadline:
            raise SystemExit("decomp server busy (request.txt still present)")
        time.sleep(0.1)
    if DONE_FILE.exists():
        DONE_FILE.unlink()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    # Truncate first so a failed job cannot be mistaken for the previous C.
    out_file.write_text("", encoding="utf-8")
    body = "out=" + str(out_file) + "\n" + "".join(
        f"{s:x}-{e:x}\n" for _, s, e in ranges
    )
    tmp = QUEUE / "request.txt.tmp"
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, REQ_FILE)
    while time.time() < deadline:
        if DONE_FILE.is_file():
            status = DONE_FILE.read_text(encoding="utf-8", errors="replace").strip()
            if status != "ok":
                raise SystemExit(f"decomp server: {status}")
            return
        if server_pid() is None:
            raise SystemExit("decomp server exited while a job was in flight")
        time.sleep(0.1)
    raise SystemExit(f"decomp server timed out after {timeout}s")


def stop_server() -> int:
    QUEUE.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text("stop\n", encoding="utf-8")
    pid = server_pid()
    print(f"[decomp] stop requested" + (f" (pid {pid})" if pid else ""))
    return 0


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
    ap.add_argument(
        "--serve",
        action="store_true",
        help="keep one Ghidra open and decompile jobs from the queue",
    )
    ap.add_argument("--stop", action="store_true", help="ask the server to exit")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.stop:
        return stop_server()
    if args.serve:
        return serve()

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
    if server_pid():
        print(f"[decomp] queue {len(ranges)} range(s) -> {out_file}")
        wait_ready(args.timeout)
        t0 = time.time()
        enqueue(ranges, out_file, args.timeout)
        print(f"[decomp] queue round-trip {time.time() - t0:.1f}s")
    else:
        run_ghidra(ranges, out_file, args.timeout)
    text = out_file.read_text(encoding="utf-8", errors="replace")
    print(f"[decomp] wrote {len(text)} bytes to {out_file}")
    for label, s, e in ranges:
        print(f"  {label}  {hex(s)}-{hex(e)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
