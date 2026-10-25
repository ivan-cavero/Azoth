#!/usr/bin/env python3
"""Every file path a runtime tool imports must exist.

WHY THIS EXISTS
===============
The launcher's runtime tools load each other by absolute path instead of importing,
because they run injected beside the game. A path that was correct before a
reorganization breaks at RUN TIME and only when that tool is reached: MEASURED
2026-10-25, `patch-timeout-watchdog.py` raised

    FileNotFoundError: ...\\scripts\\send-input.py

because the helper had moved to `scripts/gui/send-input.py`. The game then failed to
start with two patches silently reported as FAILED, which is exactly the kind of
breakage that looks like a game problem rather than a repo problem.

This gate resolves the `HERE.parents[N] / "..."` helper paths statically and fails
when one does not exist, so a reorganization cannot leave a tool pointing at nothing.

Usage:
    python scripts/check/check-launcher-paths.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Each directory below is scanned for `HERE.parents[N] / "..."` and `REPO / "..."`
# helper paths. The runtime tools are the ones that broke the game start; scripts/
# session/ holds the same pattern and drifted for the same reason.
SCANNED_DIRS = (
    ROOT / "services" / "launcher" / "runtime-tools",
    ROOT / "scripts" / "session",
)

# `HERE.parents[N] / "a" / "b.py"` and the plain `"a/b.py"` string form used by
# importlib-based loaders. Both appear in these tools.
PARENTS_RE = re.compile(r'HERE\.parents\[(\d+)\]((?:\s*/\s*"[^"]+")+)')
REPO_RE = re.compile(r'(?:REPO|ROOT)\s*/\s*("scripts"[^,\n)]*)')
# `sys.path.insert(0, str(<base> / "reverse" / "tools"))` style imports break the
# same way. MEASURED 2026-10-25: catalog.py moved to reverse/tools/corpus/ and three
# tools kept inserting reverse/tools, so `from catalog import PE` raised
# ModuleNotFoundError at RUN time -- and inside frida-trust-patch.py it surfaced only
# as "disk-patch check skipped" because the call site swallows exceptions.
SYSPATH_RE = re.compile(r"sys\.path\.insert\(\s*0\s*,\s*str\(([^\n]+)\)\s*\)")
# The modules those inserts exist to make importable. A directory can exist while the
# module inside it does not, which is exactly the catalog.py case: reverse/tools/ was
# still there, catalog.py had moved to reverse/tools/corpus/. So an insert alone is not
# enough -- the imported module has to be findable under one of the inserted paths.
LOCAL_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([a-z_][a-z0-9_]*)\b", re.MULTILINE)


def parts_of(expr: str) -> list[str]:
    return re.findall(r'"([^"]+)"', expr)


def _installed_modules() -> set[str]:
    """Top-level importable third-party modules, so the local check does not flag them."""
    import pkgutil

    return {m.name for m in pkgutil.iter_modules()}


_INSTALLED = _installed_modules()


def main() -> int:
    files = []
    for d in SCANNED_DIRS:
        if not d.is_dir():
            print(f"check-launcher-paths: FAIL: {d} is missing", file=sys.stderr)
            return 1
        files.extend(sorted(d.glob("*.py")))
    if not files:
        print("check-launcher-paths: FAIL: no tools found", file=sys.stderr)
        return 1

    problems: list[str] = []
    checked = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        # `HERE` in these tools is `Path(__file__).resolve().parent`, i.e. already the
        # directory. So `HERE.parents[n]` is `here.parents[n]` for the same directory and
        # must NOT be shifted: getting this off by one made the first run of this gate
        # report the correct `scripts/send-input.py` location as `services/scripts/...`.
        here = path.parent
        for m in PARENTS_RE.finditer(text):
            depth = int(m.group(1))
            parts = parts_of(m.group(2))
            if not parts:
                continue
            # `Path.parents[0]` is the parent of `here`, so `HERE.parents[2]` in the tool is
            # `here.parents[2]` here and the index must match exactly, not be shifted.
            base = here if depth == 0 else here.parents[depth]
            target = base.joinpath(*parts)
            checked += 1
            if not target.exists():
                problems.append(f"{rel}: HERE.parents[{depth}] / {' / '.join(parts)} -> {target} does not exist")
        inserts: list[list[Path]] = []
        for m in SYSPATH_RE.finditer(text):
            expr = m.group(1)
            parts = parts_of(expr)
            if not parts:
                continue
            # Resolve against every plausible base: the repository root, the tool's own
            # directory, and the runtime-tools dir. At least one must exist.
            bases = [ROOT, here, ROOT / "scripts", SCANNED_DIRS[0]]
            resolved = [b.joinpath(*parts) for b in bases]
            existing = [r for r in resolved if r.exists()]
            checked += 1
            if not existing:
                problems.append(
                    f"{rel}: sys.path.insert(0, ... / {' / '.join(parts)}) -> no candidate exists "
                    f"(tried {resolved[0]})"
                )
            inserts.extend([r] for r in existing)
        # Every local module the file imports must be findable under an inserted path.
        if inserts:
            flat = [d for group in inserts for d in group]
            for mod in sorted(set(LOCAL_IMPORT_RE.findall(text))):
                if mod in sys.stdlib_module_names or mod in _INSTALLED:
                    continue
                found = any((d / f"{mod}.py").is_file() for d in flat)
                if not found:
                    problems.append(
                        f"{rel}: imports {mod!r} but none of the sys.path.insert dirs contain "
                        f"{mod}.py (searched {[str(d) for d in flat]})"
                    )
        for m in REPO_RE.finditer(text):
            parts = parts_of(m.group(1))
            if not parts:
                continue
            target = ROOT.joinpath(*parts)
            checked += 1
            if not target.exists():
                problems.append(f"{rel}: REPO / {' / '.join(parts)} -> {target} does not exist")

    if problems:
        for p in problems:
            print(f"check-launcher-paths: FAIL: {p}", file=sys.stderr)
        return 1

    print(f"check-launcher-paths: ok ({len(files)} tools, {checked} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
