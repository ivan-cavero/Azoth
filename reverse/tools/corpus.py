#!/usr/bin/env python3
"""Decompile every .pdata function of NewWorld.exe into a local corpus.

Output lives under reverse/builds/<sha256>/corpus by default.
Git ignores that directory, and the executable hash keeps builds separate.
Ghidra output is pseudocode, not matching source. Re-running resumes from
shard index files.

Usage:
  python az.py re corpus --limit 40
  python az.py re corpus
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths, decomp_corpus_dir, sha256_file  # noqa: E402
from decomp import (  # noqa: E402
    CLASS_NAME,
    PROJECT_DIR,
    PROJECT_NAME,
    WORK,
    check_install,
    classpath,
    cmd_safe_args,
    ghidra_paths,
)
from peutil import PEx  # noqa: E402

HERE = Path(__file__).resolve().parent
JAVA_SRC = HERE / "ghidra" / "DecompileCorpus.java"
CORPUS_CLASS = "DecompileCorpus.class"
VERSION_NEEDLE = b"[RETAIL].Javelin."


def compile_corpus(force: bool = False) -> Path:
    script_dir = WORK / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    compiled = list((WORK / "classes").glob("DecompileCorpus*.class"))
    fresh = bool(compiled) and not force and all(
        (script_dir / class_file.name).is_file()
        and (script_dir / class_file.name).stat().st_mtime >= JAVA_SRC.stat().st_mtime
        for class_file in compiled
    )
    if fresh:
        return script_dir
    javac = ghidra_paths()["jdk"] / "bin" / "javac.exe"
    out_dir = WORK / "classes"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [str(javac), "-nowarn", "-cp", classpath(), "-d", str(out_dir), str(JAVA_SRC)],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise SystemExit(f"javac failed:\n{res.stdout}\n{res.stderr}")
    produced = list(out_dir.glob("DecompileCorpus*.class"))
    if not (out_dir / CORPUS_CLASS).is_file():
        raise SystemExit(f"javac produced no {CORPUS_CLASS}")
    # Inner classes ($1, $Result, ...) must sit beside the outer class or
    # Ghidra's script loader dies with NoClassDefFoundError.
    for extra in script_dir.glob("DecompileCorpus*.class"):
        extra.unlink()
    for class_file in produced:
        shutil.copy2(class_file, script_dir / class_file.name)
    # Ghidra 12 resolves the script name; keep the class beside DecompileTargets.
    if not (script_dir / CLASS_NAME).is_file():
        raise SystemExit(f"missing {script_dir / CLASS_NAME}; run decomp.py --selftest once")
    return script_dir


def version_strings(path: Path) -> list[str]:
    found: set[str] = set()
    overlap = len(VERSION_NEEDLE) + 64
    prev = b""
    with path.open("rb") as handle:
        while True:
            block = handle.read(8 * 1024 * 1024)
            if not block:
                break
            data = prev + block
            start = 0
            while True:
                hit = data.find(VERSION_NEEDLE, start)
                if hit < 0:
                    break
                end = hit
                while end < len(data) and 32 <= data[end] < 127 and end - hit < 80:
                    end += 1
                found.add(data[hit:end].decode("ascii", "replace"))
                start = hit + len(VERSION_NEEDLE)
            prev = data[-overlap:]
    return sorted(found)


def deduped_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    best: dict[int, int] = {}
    for start, end in ranges:
        if end <= start:
            continue
        previous = best.get(start)
        if previous is None or end > previous:
            best[start] = end
    return sorted(best.items())


def write_ranges(path: Path, ranges: list[tuple[int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for start, end in ranges:
            handle.write(f"{start:x} {end:x}\n")


def write_readme(dest: Path, meta: dict) -> None:
    versions = ", ".join(meta["versions"]) or "(none found)"
    text = (
        "New World client pseudocode corpus\n"
        f"exe: {meta['exe']}\n"
        f"sha256: {meta['exe_sha256']}\n"
        f"version strings: {versions}\n"
        f"pdata functions: {meta['function_count']}\n"
        "\n"
        "Ghidra pseudocode for this frozen build. Not matching source.\n"
        "Each function starts with a line\n"
        "  ########## <start>-<end> status=ok name=FUN_... ##########\n"
        "Shards are shards/shard-NNNNNN.c with a sibling .idx of\n"
        "  start<TAB>status<TAB>bytes<TAB>shard\n"
        "progress.json is the live counter. Re-run corpus.py to resume.\n"
    )
    (dest / "README.txt").write_text(text, encoding="utf-8")


def launch(dest: Path, ranges_file: Path, threads: int, limit: int, timeout: int) -> int:
    problems = check_install()
    if problems:
        raise SystemExit("MISSING " + "; ".join(problems))
    if not (PROJECT_DIR / f"{PROJECT_NAME}.rep").is_dir():
        raise SystemExit(
            "[corpus] no cached Ghidra project; run decomp.py --selftest once so "
            "the exe is imported"
        )
    script_dir = compile_corpus()
    g = ghidra_paths()
    args = [
        str(g["headless"]),
        str(PROJECT_DIR),
        PROJECT_NAME,
        "-process",
        "NewWorld.exe",
        "-noanalysis",
        "-readOnly",
        "-scriptPath",
        str(script_dir),
        "-postScript",
        CORPUS_CLASS,
    ]
    env = dict(os.environ)
    env["JAVA_HOME"] = str(g["jdk"])
    # Ghidra 12.1.4 reads GHIDRA_MAXMEM / GHIDRA_HEADLESS_MAXMEM (default 2G);
    # it does NOT read MAXMEM, so the old assignment was silently a no-op.
    heap = env.get("AZOTH_DECOMP_MAXMEM", "12G")
    env["GHIDRA_MAXMEM"] = heap
    env["GHIDRA_HEADLESS_MAXMEM"] = heap
    env["DECOMP_CORPUS_DIR"] = str(dest)
    env["DECOMP_CORPUS_RANGES"] = str(ranges_file)
    env["DECOMP_CORPUS_THREADS"] = str(threads)
    env["DECOMP_CORPUS_LIMIT"] = str(limit)
    env["DECOMP_CORPUS_TIMEOUT"] = str(timeout)
    env["DECOMP_CORPUS_CHUNK"] = "1024"
    log_path = dest / "corpus.log"
    print(f"[corpus] launching -> {dest}", flush=True)
    print(f"[corpus] log {log_path}", flush=True)
    log = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        ["cmd.exe", "/c", *cmd_safe_args([str(args[0]), *args[1:]])],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    (dest / "corpus.pid").write_text(str(proc.pid), encoding="utf-8")
    print(f"[corpus] pid={proc.pid}", flush=True)
    return proc.pid


def prepare(dest: Path, exe: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(exe)
    versions = version_strings(exe)
    print(f"[corpus] sha256 {digest}", flush=True)
    print(f"[corpus] versions {versions or '(none)'}", flush=True)
    pex = PEx(exe)
    ranges = deduped_ranges(pex.ranges)
    ranges_file = dest / "ranges.txt"
    if not ranges_file.is_file() or ranges_file.stat().st_size == 0:
        print(f"[corpus] writing {len(ranges)} ranges", flush=True)
        write_ranges(ranges_file, ranges)
    meta = {
        "exe": str(exe),
        "exe_sha256": digest,
        "exe_size": exe.stat().st_size,
        "exe_mtime": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(exe.stat().st_mtime)
        ),
        "image_base": hex(pex.pe.image_base),
        "versions": versions,
        "function_count": len(ranges),
        "ghidra": ghidra_paths()["headless"].parents[1].name,
        "kind": "ghidra-pseudocode",
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    write_readme(dest, meta)
    progress = dest / "progress.json"
    if not progress.is_file():
        progress.write_text(
            json.dumps({"status": "launching", "total": len(ranges), "finished": 0})
            + "\n",
            encoding="utf-8",
        )
    return meta


def corpus_dir(exe: Path) -> Path:
    return decomp_corpus_dir(exe)


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk-decompile NewWorld.exe")
    ap.add_argument("--limit", type=int, default=0, help="attempt only N functions")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=60, help="seconds per function")
    ap.add_argument(
        "--wait",
        action="store_true",
        help="block until the Ghidra process exits (smoke runs)",
    )
    args = ap.parse_args()

    exe = default_paths()["exe"]
    if not exe.is_file():
        raise SystemExit(f"[corpus] exe missing: {exe}")
    print("[corpus] identifying exe", flush=True)
    digest = sha256_file(exe)
    dest = corpus_dir(exe)
    meta = prepare(dest, exe)
    if meta["exe_sha256"] != digest:
        raise SystemExit("[corpus] executable changed while preparing")
    progress = json.loads((dest / "progress.json").read_text(encoding="utf-8"))
    if progress.get("status") == "complete" and args.limit == 0:
        print(f"[corpus] already complete at {dest}")
        return 0
    pid_file = dest / "corpus.pid"
    if pid_file.is_file():
        from decomp import pid_alive

        try:
            old = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            old = 0
        if old and pid_alive(old):
            print(f"[corpus] already running pid={old} at {dest}")
            return 0
    launch(dest, dest / "ranges.txt", args.threads, args.limit, args.timeout)
    if not args.wait:
        print(f"[corpus] background dump of {meta['function_count']} functions")
        return 0
    pid = int((dest / "corpus.pid").read_text(encoding="utf-8").strip())
    from decomp import pid_alive

    while pid_alive(pid):
        time.sleep(2)
    progress = json.loads((dest / "progress.json").read_text(encoding="utf-8"))
    print(f"[corpus] exited status={progress.get('status')} {dest}")
    return 0 if progress.get("status") == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
