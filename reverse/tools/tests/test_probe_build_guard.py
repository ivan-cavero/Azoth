"""The build guard in reverse/probes/client/_paths.py, tested where it is needed.

WHY THIS EXISTS. A probe hardcodes virtual addresses, and a VA only means
something for the build it was derived on. The failure mode is silent: Frida's
`Interceptor.attach` succeeds on any address, so a probe built for 1.400 hooks
unrelated code on 1.460 and writes a capture that looks like a measurement. This
was measured, not imagined -- at `0x14087b5c0` the current build has
movhps/movaps/mulps float arithmetic where the probe expects a varint branch
ladder.

The guard must therefore fail CLOSED. The three behaviours worth pinning are that
a known build passes, a different build refuses, and a probe that cannot state a
build refuses rather than assuming the best.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROBES = Path(__file__).resolve().parents[2] / "probes" / "client"
sys.path.insert(0, str(PROBES))

import _paths  # noqa: E402


class BuildGuardTest(unittest.TestCase):
    def test_the_current_runtime_copy_is_readable(self):
        """The hash comes from the exe the launcher runs, not from the Steam install.

        The private copy differs from the install by the DTLS bypass, so a guard
        that hashed the install would describe code that never runs.
        """
        digest = _paths.runtime_build_sha256()
        self.assertTrue(digest, f"could not read {_paths.RUNTIME_EXE}")
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_a_matching_build_attaches(self):
        """No exception when the probe's build matches what would be launched."""
        _paths.require_build(_paths.runtime_build_sha256(), "test-probe")

    def test_a_different_build_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            _paths.require_build("0" * 64, "test-probe")
        message = str(caught.exception)
        self.assertIn("build mismatch", message)
        # The message has to say WHY this is dangerous, because the operator's
        # instinct on a mismatch is to bypass the check.
        self.assertIn("measures unrelated code", message)

    def test_no_build_claim_is_refused(self):
        """A probe that cannot name its build must not run on the benefit of the doubt."""
        with self.assertRaises(SystemExit) as caught:
            _paths.require_build("", "test-probe")
        self.assertIn("NO build claim", str(caught.exception))

    def test_the_fragment_probe_states_no_build_it_cannot_verify(self):
        """frida-fragment-grammar's VAs are 1.400 and no 1.400 hash was ever recorded.

        The honest state for it is an empty claim, which the guard refuses. If
        someone later re-derives the VAs and fills the constant in, this test is
        the reminder to replace it with a real build assertion rather than deleting
        it.
        """
        import importlib.util

        path = PROBES / "frida-fragment-grammar.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn("PROBE_BUILD_SHA256 = \"\"", source)
        # And it must actually use the guard, not merely declare the constant.
        self.assertIn("require_build(PROBE_BUILD_SHA256", source)
        spec = importlib.util.spec_from_file_location("_frag_grammar", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass  # a probe that refuses at import is still a probe that refuses
        self.assertEqual(module.PROBE_BUILD_SHA256, "")


if __name__ == "__main__":
    unittest.main()
