"""LyShine UI asset classifier tests (stdlib unittest).

The classifier is a pure read over the PAK index, so it can be trusted without
the 408 MB real database: these tests build a small synthetic index in a temp
directory, classify it, and check the counts. One selftest-shaped test confirms
the tool skips gracefully when the real index is absent.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uiassets  # noqa: E402

SCHEMA = """
CREATE TABLE entry (
    path   TEXT NOT NULL,
    pak    TEXT NOT NULL,
    ext    TEXT NOT NULL,
    csize  INTEGER NOT NULL,
    usize  INTEGER NOT NULL,
    crc    INTEGER NOT NULL,
    method INTEGER NOT NULL
);
"""

# (path, csize, usize, method) — a miniature index with one of every kind and
# two paths that must NOT count as UI assets.
ROWS = [
    ("lyshineui/_common/baseelement.luac", 100, 200, 15),
    ("lyshineui/_samples/styleguide.dynamicuicanvas", 300, 400, 15),
    ("lyshineui/hud/health.dds", 500, 600, 8),
    ("lyshineui/fonts/main.font", 7, 9, 0),
    ("localization/es-mx/dialogue.loc.xml", 11, 22, 0),
    ("world/textures/rock.dds", 900, 1000, 15),
    ("libs/config/defaultprofile.xml", 13, 14, 0),
]


def make_index(directory: pathlib.Path) -> pathlib.Path:
    db = directory / "pakindex.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO entry VALUES (?,?,?,?,?,?,?)",
        [(p, "DataStrm-part1.pak", pathlib.PurePosixPath(p).suffix.lstrip("."),
          cs, us, 0, m) for p, cs, us, m in ROWS],
    )
    con.commit()
    con.close()
    return db


class ClassifyTest(unittest.TestCase):
    def test_each_kind_by_path_and_extension(self) -> None:
        self.assertEqual(uiassets.classify("lyshineui/_common/baseelement.luac"), "luac")
        self.assertEqual(
            uiassets.classify("lyshineui/_samples/styleguide.dynamicuicanvas"), "canvas")
        self.assertEqual(uiassets.classify("lyshineui/hud/health.dds"), "dds")
        self.assertEqual(uiassets.classify("lyshineui/fonts/main.font"), "other")
        self.assertEqual(uiassets.classify("localization/es-mx/x.loc.xml"), "loc")

    def test_path_outside_lyshineui_is_not_a_ui_asset(self) -> None:
        self.assertIsNone(uiassets.classify("world/textures/rock.dds"))
        self.assertIsNone(uiassets.classify("libs/config/defaultprofile.xml"))

    def test_windows_separators_are_normalized(self) -> None:
        self.assertEqual(uiassets.classify("lyshineui\\hud\\health.dds"), "dds")


class ScanTest(unittest.TestCase):
    def test_counts_and_histograms_cover_the_classified_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kinds = uiassets.scan(make_index(pathlib.Path(tmp)))
            self.assertEqual(kinds["luac"]["count"], 1)
            self.assertEqual(kinds["canvas"]["count"], 1)
            self.assertEqual(kinds["dds"]["count"], 1)
            self.assertEqual(kinds["other"]["count"], 1)
            self.assertEqual(kinds["loc"]["count"], 1)
            self.assertEqual(kinds["luac"]["csize"], 100)
            self.assertEqual(kinds["luac"]["usize"], 200)
            self.assertEqual(kinds["luac"]["methods"], {15: 1})
            self.assertEqual(kinds["other"]["methods"], {0: 1})

    def test_non_ui_paths_are_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kinds = uiassets.scan(make_index(pathlib.Path(tmp)))
            total = sum(b["count"] for b in kinds.values())
            self.assertEqual(total, 5)  # world/ and libs/ excluded

    def test_document_shape_and_lyshineui_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = uiassets.build_document(make_index(pathlib.Path(tmp)))
            self.assertEqual(document["evidence"], "measured")
            self.assertEqual(document["rules"], uiassets.RULES)
            # canvas + luac + dds + other, loc is tracked separately.
            self.assertEqual(document["totals"]["lyshineui"], 4)
            self.assertEqual(document["totals"]["classified"], 5)
            self.assertEqual(document["kinds"]["dds"]["sample"][0]["path"],
                             "lyshineui/hud/health.dds")


class SelftestTest(unittest.TestCase):
    def test_absent_index_skips_gracefully(self) -> None:
        missing = pathlib.Path(tempfile.gettempdir()) / "definitely-absent-pakindex.db"
        # selftest prints; keep the suite output clean and deterministic.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(uiassets.selftest(missing), 0)

    def test_synthetic_index_fails_the_real_baseline(self) -> None:
        # The synthetic index does not match the measured 1.460 baseline, so the
        # selftest must say so rather than pass on any index it is handed.
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(uiassets.selftest(make_index(pathlib.Path(tmp))), 1)


if __name__ == "__main__":
    unittest.main()
