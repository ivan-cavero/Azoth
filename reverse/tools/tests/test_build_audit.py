"""build-audit tests (stdlib unittest).

`scripts/ops/build-audit.py` is the one re-runnable command that regenerates
every generated inventory artifact from the installed client build and proves
the tracked copy still reproduces, so a stale artifact can never silently pass
as current again. Three properties have to hold:

* a fresh run exits 0 and prints one PASS/FAIL line per artifact in the table;
* the run is READ-ONLY: `git status --short` is byte-identical before and after,
  which is the property the audit is built around;
* a corrupted regeneration is reported as FAIL. This is driven through the
  module's own comparison function against a temp dir, so a tracked artifact is
  never corrupted by the test.

The fresh-run test drives the real installed client (that is the point of the
audit); the corruption test stays synthetic and offline.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
AUDIT = REPO / "scripts" / "ops" / "build-audit.py"

# The six tracked artifacts named by the audit table, in print order.
ARTIFACTS = (
    "research/atlas/az-type-registry.json",
    "research/atlas/aoi-trait-registry.json",
    "research/atlas/javelin-messages.json",
    "research/derived/wire-type-names.json",
    "research/derived/client-facet-factories.json",
    "research/derived/rtti-classes.json",
)


def load_audit():
    """Import the hyphenated build-audit module the way the repo does."""
    spec = importlib.util.spec_from_file_location("build_audit", AUDIT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_audit"] = module
    spec.loader.exec_module(module)
    return module


def git_status() -> str:
    return subprocess.run(
        ["git", "status", "--short"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class FreshRunTest(unittest.TestCase):
    def test_fresh_run_exits_zero_and_lines_every_artifact(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(AUDIT)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for rel in ARTIFACTS:
            self.assertIn(f"PASS {rel}", proc.stdout, proc.stdout)
        self.assertRegex(proc.stdout, r"build-audit: \d+ pass, \d+ fail")


class ReadOnlyTest(unittest.TestCase):
    def test_run_leaves_the_working_tree_unchanged(self) -> None:
        before = git_status()
        subprocess.run(
            [sys.executable, str(AUDIT)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        self.assertEqual(before, git_status())


class CorruptedCopyTest(unittest.TestCase):
    def test_compare_artifact_reports_fail_for_a_corrupted_copy(self) -> None:
        audit = load_audit()
        tracked = REPO / "research" / "derived" / "client-facet-factories.json"
        with tempfile.TemporaryDirectory() as tmp:
            gen = pathlib.Path(tmp) / "client-facet-factories.json"

            gen.write_bytes(tracked.read_bytes())
            ok, _reason, _note = audit.compare_artifact(tracked, gen)
            self.assertTrue(ok)

            gen.write_bytes(b'{"corrupted": true}\n')
            ok, reason, _note = audit.compare_artifact(tracked, gen)
            self.assertFalse(ok)
            self.assertTrue(reason)


class StaleBuildGateTest(unittest.TestCase):
    """The build-identity gate FAILs an artifact whose declared build is stale.

    Driven through the module's own `build_mismatch` against temp fixtures, so a
    tracked artifact is never touched. Uses the real installed SHA-256 for the
    positive case, so the gate is proven against the value it must accept.
    """

    def test_gate_fails_a_fixture_declaring_another_build(self) -> None:
        audit = load_audit()
        installed = audit.installed_sha256()
        self.assertTrue(installed)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)

            stale = path / "stale.json"
            stale.write_text(
                json.dumps({"build_sha256": "8654f01d324636d9" + "0" * 48}),
                encoding="utf-8",
            )
            self.assertTrue(audit.build_mismatch(stale, "build_sha256", installed))

            fresh = path / "fresh.json"
            fresh.write_text(json.dumps({"build_sha256": installed}), encoding="utf-8")
            self.assertEqual(audit.build_mismatch(fresh, "build_sha256", installed), "")

            missing = path / "missing.json"
            missing.write_text(json.dumps({"other": "x"}), encoding="utf-8")
            self.assertTrue(audit.build_mismatch(missing, "build_sha256", installed))

    def test_prefix_field_accepts_only_a_prefix_of_installed(self) -> None:
        audit = load_audit()
        installed = audit.installed_sha256()
        self.assertTrue(installed)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)

            pref = path / "pref.json"
            pref.write_text(
                json.dumps({"exe_sha256_prefix": installed[:16]}), encoding="utf-8"
            )
            self.assertEqual(
                audit.build_mismatch(pref, "exe_sha256_prefix", installed, True), ""
            )

            stale = path / "stale.json"
            stale.write_text(
                json.dumps({"exe_sha256_prefix": "8654f01d324636d9"}),
                encoding="utf-8",
            )
            self.assertTrue(
                audit.build_mismatch(stale, "exe_sha256_prefix", installed, True)
            )


if __name__ == "__main__":
    unittest.main()
