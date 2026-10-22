"""PAK index tests (stdlib unittest).

The summary is a provenance record: it says which client build the content
inventory belongs to. A hardcoded hash makes every rebuild claim the build it
was written for, not the build it indexed.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pakindex  # noqa: E402


class ExeShaPrefixTest(unittest.TestCase):
    def test_reports_the_hash_of_the_file_it_is_given(self) -> None:
        payload = b"not a real executable, but its hash is what matters"
        with tempfile.TemporaryDirectory() as tmp:
            exe = pathlib.Path(tmp) / "NewWorld.exe"
            exe.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()[:16]
            self.assertEqual(pakindex.exe_sha256_prefix(exe), expected)

    def test_two_different_files_give_different_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = pathlib.Path(tmp) / "a.exe"
            b = pathlib.Path(tmp) / "b.exe"
            a.write_bytes(b"build one")
            b.write_bytes(b"build two")
            self.assertNotEqual(
                pakindex.exe_sha256_prefix(a), pakindex.exe_sha256_prefix(b)
            )

    def test_missing_file_does_not_claim_a_build(self) -> None:
        missing = pathlib.Path(tempfile.gettempdir()) / "definitely-absent-nw.exe"
        self.assertIsNone(pakindex.exe_sha256_prefix(missing))


if __name__ == "__main__":
    unittest.main()
