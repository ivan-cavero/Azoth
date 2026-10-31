#!/usr/bin/env python3
"""build-audit - prove every generated inventory artifact still reproduces.

For each artifact the audit first reads the artifact's own declared build field
(`build_sha256`, or `exe_sha256_prefix` for rtti-classes.json) and FAILs the row
when it is not the installed build's SHA-256 (`installed.sha256` in
research/atlas/builds.json). That build identity is the primary detector: it is
the only staleness signal for the tools that have no `--out` form (az-types,
trait-registry, message-registry, rtti), so no row can hide a stale artifact.
Where a tool does have an `--out` form the audit then regenerates it from the
installed client into a temp directory (never onto the tracked path) and
byte-compares the result with the tracked file as a second, stronger check. It
prints one `PASS <path>` / `FAIL <path>  <reason>` line per artifact, a
`PASS/FAIL worktree` line for its own read-only self-check, and a final
`build-audit: N pass, M fail`. Exit 0 when everything passes, 1 otherwise.

READ-ONLY, and that is the point: the audit captures `git status --short` and
`git diff --stat` before and after the run and fails if the tree moved. The two
scanners whose `--check` is a misnomer (scan-wire-names, scan-client-facets write
the tracked file as a side effect) are therefore run with `--out <tmp>` and
byte-compared, never with their default output path.

  python ef.py run build-audit
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "reverse" / "tools"
BUILDS = REPO / "research" / "atlas" / "builds.json"

# tracked artifact -> how to regenerate it. `kind`:
#   check     run `<tool> --check`, read-only; PASS means its pinned invariants
#             reproduce (the tool emits no artifact to compare).
#   out       run `<tool> --exe <installed> --out <tmp>`, then byte-compare.
#   selftest  run `<tool> selftest`, read-only; PASS means the scanner still
#             works against the tracked artifact, not that it was compared.
# `build_field` is the artifact's own declared build identity; `build_is_prefix`
# is set when that field holds only a hash prefix (rtti-classes.json). Every
# artifact must carry one -- it is the row's staleness detector.
@dataclass(frozen=True)
class Spec:
    tracked: str
    tool: str
    kind: str
    outname: str = ""
    typeindex: str = ""
    build_field: str = "build_sha256"
    build_is_prefix: bool = False


ARTIFACTS: tuple[Spec, ...] = (
    Spec("research/atlas/az-type-registry.json", "type/scan-az-types.py", "check"),
    Spec("research/atlas/aoi-trait-registry.json", "type/scan-trait-registry.py", "check"),
    Spec("research/atlas/javelin-messages.json", "type/scan-message-registry.py", "check"),
    Spec(
        "research/derived/wire-type-names.json",
        "type/scan-wire-names.py",
        "out",
        outname="wire-type-names.json",
        typeindex="private-client/runtime/typeindex.json",
    ),
    Spec(
        "research/derived/client-facet-factories.json",
        "type/scan-client-facets.py",
        "out",
        outname="client-facet-factories.json",
    ),
    Spec(
        "research/derived/rtti-classes.json",
        "type/rtti.py",
        "selftest",
        build_field="exe_sha256_prefix",
        build_is_prefix=True,
    ),
)


@dataclass
class Result:
    path: str
    ok: bool
    reason: str = ""
    note: str = ""


def installed_sha256() -> str:
    """The installed build's full SHA-256 from builds.json, or '' if absent."""
    try:
        data = json.loads(BUILDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    sha = data.get("installed", {}).get("sha256", "")
    return sha if isinstance(sha, str) else ""


def build_mismatch(
    declared_at: Path, build_field: str, installed_sha: str, is_prefix: bool = False
) -> str:
    """Return a FAIL reason if `declared_at`'s build field is not the installed
    build, or '' when it matches. A missing/empty field always fails closed."""
    if not installed_sha:
        return "installed build sha256 unavailable (research/atlas/builds.json)"
    try:
        declared = json.loads(declared_at.read_text(encoding="utf-8")).get(build_field)
    except (OSError, ValueError) as exc:
        return f"cannot read declared {build_field}: {exc}"
    if not isinstance(declared, str) or not declared:
        return f"declares no {build_field}"
    matches = installed_sha.startswith(declared) if is_prefix else declared == installed_sha
    if matches:
        return ""
    return f"declared {build_field} {declared[:16]} != installed {installed_sha[:16]}"


def installed_exe() -> Path | None:
    """The installed client the scanners default to, or None if it is absent."""
    sys.path.insert(0, str(TOOLS))
    try:
        from common import default_paths  # noqa: PLC0415

        exe = Path(default_paths()["exe"])
    except Exception:
        return None
    return exe if exe.is_file() else None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)


def _tool_missing(proc: subprocess.CompletedProcess[str]) -> bool:
    blob = (proc.stdout or "") + (proc.stderr or "")
    return "executable not found" in blob or "No such file" in blob


def _summary(proc: subprocess.CompletedProcess[str]) -> str:
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return lines[-1] if lines else f"exit {proc.returncode}"


def compare_artifact(tracked: Path, generated: Path) -> tuple[bool, str, str]:
    """Regenerated vs tracked. Returns (ok, reason, note).

    A note is set when the bytes differ but the parsed JSON is identical (a
    timestamp, key order, or whitespace), so the comparison moved to the stable
    semantic payload instead of papering the instability over.
    """
    if not tracked.is_file():
        return False, "tracked artifact missing", ""
    if not generated.is_file():
        return False, "regeneration produced no output", ""
    fresh = generated.read_bytes()
    old = tracked.read_bytes()
    if fresh == old:
        return True, "", ""
    try:
        same = json.loads(fresh.decode("utf-8")) == json.loads(old.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        same = False
    if same:
        note = (
            f"  note: {tracked.relative_to(REPO)} output is not byte-stable "
            f"(key order/whitespace); compared on parsed JSON"
        )
        return True, "", note
    return False, "differs from tracked", ""


def check(spec: Spec, tmp: Path, exe: Path | None, installed_sha: str) -> Result:
    tracked = REPO / spec.tracked
    tool = TOOLS / spec.tool
    if not tool.is_file():
        return Result(spec.tracked, False, "tool missing")
    if not tracked.is_file():
        return Result(spec.tracked, False, "tracked artifact missing")

    # Build identity is the row's primary staleness gate; only an artifact whose
    # declared build is the installed build may reach the (stronger) --out check.
    mismatch = build_mismatch(
        tracked, spec.build_field, installed_sha, spec.build_is_prefix
    )
    if mismatch:
        return Result(spec.tracked, False, mismatch)

    if spec.kind in {"check", "selftest"}:
        argv = [sys.executable, str(tool)]
        argv += ["--check"] if spec.kind == "check" else ["selftest"]
        proc = _run(argv)
        if proc.returncode != 0:
            reason = "tool missing" if _tool_missing(proc) else _summary(proc)
            return Result(spec.tracked, False, reason)
        if spec.kind == "selftest":
            reason = (
                f"{_summary(proc)} -- scanner works; "
                "rtti.py has no regenerate-to-temp form, artifact not compared"
            )
            return Result(spec.tracked, True, reason)
        return Result(spec.tracked, True)

    # kind == "out": regenerate into the temp dir, then byte-compare.
    generated = tmp / spec.outname
    argv = [sys.executable, str(tool)]
    if exe is not None:
        argv += ["--exe", str(exe)]
    if spec.typeindex:
        argv += ["--typeindex", spec.typeindex]
    argv += ["--out", str(generated)]
    proc = _run(argv)
    if proc.returncode != 0 and not generated.is_file():
        reason = "tool missing" if _tool_missing(proc) else _summary(proc)
        return Result(spec.tracked, False, reason)
    ok, reason, note = compare_artifact(tracked, generated)
    return Result(spec.tracked, ok, reason, note)


def git_snapshot() -> str:
    status = _run(["git", "status", "--short"])
    diff = _run(["git", "diff", "--stat"])
    return (status.stdout or "") + "\x00" + (diff.stdout or "")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)

    before = git_snapshot()
    exe = installed_exe()
    installed_sha = installed_sha256()
    with tempfile.TemporaryDirectory() as tmp:
        results = [check(spec, Path(tmp), exe, installed_sha) for spec in ARTIFACTS]
    after = git_snapshot()
    results.append(
        Result(
            "worktree",
            before == after,
            "changed during the audit (git status --short / git diff --stat moved)"
            if before != after
            else "",
        )
    )

    for r in results:
        if r.ok and r.reason:
            print(f"PASS {r.path}  {r.reason}")
        elif r.ok:
            print(f"PASS {r.path}")
        else:
            print(f"FAIL {r.path}  {r.reason}")
        if r.note:
            print(r.note)

    passed = sum(1 for r in results if r.ok)
    failed = len(results) - passed
    print(f"build-audit: {passed} pass, {failed} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
