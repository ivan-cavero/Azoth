"""The differential field measurer's own logic, on synthetic bodies.

WHY THIS EXISTS. `field-differential.py` reports field boundaries by looking for where
byte variability starts and stops in a set of bodies of one type. That inference is
fragile in ways a real corpus hides: it is easy to write a version that pads short
bodies (inventing bytes that are not on the wire), that treats a 200-byte body's absent
tail as a constant, or that reports "no variation" as success when it means the corpus
was a replayed capture.

These tests pin the behaviours that decide whether a report is trustworthy, using
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


class PrefixedContainerTest(unittest.TestCase):
    """The container marker moves by two bytes when the record carries an ff ff prefix.

    Measured 2026-10-26 on a live movement session: 7 of 60 channel-1 records had the
    prefix and `alc.split_container` rejected every one, because it only knows offset 24.
    The rejection is silent at the call site -- caught, counted as a non-match, reported as
    a corpus with almost no input stream -- which is the failure these tests exist to stop.
    """

    PREFIX = b"\xff\xff"
    FILLER = bytes([0x11])
    BODY = bytes([0xAA, 0xBB])

    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def _container(self, *, prefixed: bool) -> bytes:
        from azoth_world.javelin.bundle import encode_type_marker

        # The marker sits at 24 normally and at 26 when an `ff ff` prefix precedes the
        # container, so the payload is two bytes longer -- the prefix displaces it rather
        # than sitting inside the existing 24 bytes.
        #
        # `encode_type_marker` already emits the `00 01` marker followed by the prefix
        # varint, so it must NOT be preceded by a separate marker; doing that builds a
        # payload with two markers and no container decoder can read it.
        marker_at = 26 if prefixed else 24
        head = bytearray(marker_at)
        if prefixed:
            head[0:2] = self.PREFIX
            head[2:marker_at] = self.FILLER * (marker_at - 2)
        else:
            head[0:marker_at] = self.FILLER * marker_at
        return bytes(head) + encode_type_marker(0x635) + self.BODY

    def test_marker_at_24_is_read(self):
        body = self.tool._channel1_body(self._container(prefixed=False))
        self.assertIsNotNone(body, "unprefixed container must be recognised")
        self.assertTrue(body.endswith(self.BODY))

    def test_marker_at_26_with_prefix_is_read(self):
        body = self.tool._channel1_body(self._container(prefixed=True))
        self.assertIsNotNone(body, "ff-prefixed container must be recognised too")
        self.assertTrue(body.endswith(self.BODY))

    def test_a_different_type_is_not_mistaken_for_the_stream(self):
        from azoth_world.javelin.bundle import encode_type_marker

        payload = bytes(24) + encode_type_marker(0x663) + bytes([0x01])
        self.assertIsNone(self.tool._channel1_body(payload))

    def test_the_type_marker_is_read_off_the_wire(self):
        from azoth_world.javelin.bundle import encode_type_marker, read_type_marker

        payload = encode_type_marker(0x635) + bytes([0xDE, 0xAD])
        type_id, offset = read_type_marker(payload)
        self.assertEqual(type_id, 0x635)
        self.assertEqual(payload[offset:], bytes([0xDE, 0xAD]))


class CompressionDetectionTest(unittest.TestCase):
    """`CarrierEnvelope` has no `compressed` attribute, and believing it did cost 98%.

    Measured 2026-10-26: a tool that asked `getattr(envelope, "compressed", False)` always
    got False, so LZ4-compressed datagrams went into `parse_datagram` untouched. The result
    did not look broken -- it produced 3,802 channel-3 records and 60 channel-1 records out
    of 3,810 datagrams -- so the corpus appeared to contain almost no input stream. The
    truth was 3,830 channel-1 bodies. Compression is decided by the Carrier type byte, 0x81,
    and nothing else.
    """

    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def test_type_byte_0x80_is_not_decompressed(self):
        class Envelope:
            type_byte = 0x80

        body = bytes([0x20, 0x00, 0x06])
        self.assertEqual(self.tool._decompress(Envelope(), body), body)

    def test_type_byte_0x81_is_decompressed(self):
        from azoth_world.javelin.lz4 import decompress_lz4_block

        class Envelope:
            type_byte = 0x81

        # A minimal LZ4 block of pure literals: token nibble 0xF0 would need a length
        # extension, so use a short literal run: high nibble = length, then the literals.
        payload = bytes([0x30]) + b"abc"
        self.assertEqual(decompress_lz4_block(payload), b"abc")
        self.assertEqual(self.tool._decompress(Envelope(), payload), b"abc")

    def test_the_envelope_really_has_no_compressed_attribute(self):
        """Pin the trap itself, so nobody reintroduces the getattr that silently misfires."""
        from azoth_world.javelin.frame import CarrierEnvelope

        self.assertFalse(hasattr(CarrierEnvelope, "compressed"))
        self.assertFalse(hasattr(CarrierEnvelope, "compressed_size"))


class CatalogTest(unittest.TestCase):
    def test_the_tool_is_registered(self):
        import json

        catalog = json.loads((TOOLS / "catalog.json").read_text(encoding="utf-8"))
        self.assertIn("field-differential", catalog["workflows"])
        self.assertIn("field-differential", catalog["files"])
        self.assertTrue((TOOLS / "type" / "field-differential.py").is_file())


if __name__ == "__main__":
    unittest.main()
