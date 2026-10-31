"""RTTI scan provenance tests (stdlib unittest).

The scan output is a provenance record: it says which client build the RTTI
pool was read from. A hardcoded prefix makes every rebuild claim the build it
was written for, not the build it scanned -- the exact defect build-audit.py
exists to catch. Mirrors reverse/tools/tests/test_pakindex.py.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rtti  # noqa: E402


class ExeShaPrefixTest(unittest.TestCase):
    def test_reports_the_hash_of_the_file_it_is_given(self) -> None:
        payload = b"not a real executable, but its hash is what matters"
        with tempfile.TemporaryDirectory() as tmp:
            exe = pathlib.Path(tmp) / "NewWorld.exe"
            exe.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()[:16]
            self.assertEqual(rtti.exe_sha256_prefix(exe), expected)

    def test_two_different_files_give_different_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = pathlib.Path(tmp) / "a.exe"
            b = pathlib.Path(tmp) / "b.exe"
            a.write_bytes(b"build one")
            b.write_bytes(b"build two")
            self.assertNotEqual(
                rtti.exe_sha256_prefix(a), rtti.exe_sha256_prefix(b)
            )

    def test_missing_file_does_not_claim_a_build(self) -> None:
        missing = pathlib.Path(tempfile.gettempdir()) / "definitely-absent-nw.exe"
        self.assertIsNone(rtti.exe_sha256_prefix(missing))


if __name__ == "__main__":
    unittest.main()
