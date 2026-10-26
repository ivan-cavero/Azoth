"""The differential field measurer's own logic, on synthetic bodies.

WHY THIS EXISTS. `field-differential.py` reports field boundaries by looking for where
byte variability starts and stops in a set of bodies of one type. That inference is
fragile in ways a real corpus hides: it is easy to write a version that pads short
bodies (inventing bytes that are not on the wire), that treats a 200-byte body's absent
tail as a constant, or that reports "no variation" as success when it means the corpus
was a replayed capture.

These tests pin the three behaviours that decide whether a report is trustworthy, using
hand-built bodies where the right answer is known rather than measured.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]


def load_tool():
    for entry in (str(TOOLS), str(TOOLS / "type")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    sys.path.insert(0, str(REPO / "services" / "world" / "src"))
    spec = importlib.util.spec_from_file_location(
        "field_differential_under_test", TOOLS / "type" / "field-differential.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VariabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def test_a_constant_offset_is_reported_constant(self):
        bodies = [bytes([0xAA, n, 0x01]) for n in range(20)]
        report = self.tool.variability(bodies)
        columns = report["columns"]
        self.assertFalse(columns[0]["varies"], "tag byte never changes")
        self.assertTrue(columns[1]["varies"], "counter changes every sample")
        self.assertFalse(columns[2]["varies"])

    def test_runs_collapse_to_contiguous_regions(self):
        bodies = [bytes([0x00, n, 0x00, 0xFF]) for n in range(10)]
        runs = self.tool.regions(self.tool.variability(bodies)["columns"])
        self.assertEqual(runs, [(0, 0, False), (1, 1, True), (2, 3, False)])

    def test_short_bodies_are_not_padded(self):
        """A shorter body means the tail fields were absent, not zero.

        Padding would report the tail as "constant 0x00" -- a phantom field -- which is
        exactly the kind of fabricated structure this tool must not produce.
        """
        bodies = [bytes([0x01, 0x02]), bytes([0x03, 0x04, 0x05])]
        report = self.tool.variability(bodies)
        self.assertEqual(report["lengths"], [2, 3])
        self.assertEqual(report["columns"][2]["absent"], 1, "one body has no third byte")
        self.assertEqual(report["columns"][0]["absent"], 0)

    def test_identical_bodies_are_reported_as_no_variation(self):
        """A replayed capture looks exactly like this, and must not read as success."""
        bodies = [bytes([0x10, 0x20, 0x30])] * 25
        report = self.tool.variability(bodies)
        self.assertFalse(any(c["varies"] for c in report["columns"]))
        self.assertEqual(self.tool.regions(report["columns"]), [(0, 2, False)])

    def test_the_type_marker_is_read_off_the_wire_not_assumed(self):
        """Guard the extraction contract: body offsets start after the marker."""
        from azoth_world.javelin.bundle import encode_type_marker, read_type_marker

        payload = encode_type_marker(0x635) + b"\xde\xad\xbe\xef"
        type_id, offset = read_type_marker(payload)
        self.assertEqual(type_id, 0x635)
        self.assertEqual(payload[offset:], b"\xde\xad\xbe\xef")


class CatalogTest(unittest.TestCase):
    def test_the_tool_is_registered(self):
        import json

        catalog = json.loads((TOOLS / "catalog.json").read_text(encoding="utf-8"))
        self.assertIn("field-differential", catalog["workflows"])
        self.assertIn("field-differential", catalog["files"])
        self.assertTrue((TOOLS / "type" / "field-differential.py").is_file())


if __name__ == "__main__":
    unittest.main()
