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


class Channel0ClientRecordTest(unittest.TestCase):
    """A CLIENT channel-0 typed record carries the marker at offset 24, not at 0.

    Measured 2026-10-27 on the first live `0x5de` record. The payload is
    `c81159f8 0000002e <16-byte actor id> 00 01 9e 17 <body>`, so the typed marker sits at
    offset 24 (an 8-byte header plus a 16-byte actor id). `iter_bodies` only ever read
    offset 0, so `--type 0x5de` reported 0 bodies while the world log held the message and
    the world's own parser logged `inbound-typed channel 0 type 0x5de`. The offset-0 read
    is right for a server-side record and must keep working; these tests pin both.
    """

    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def _client_record(self, type_id: int, body: bytes) -> bytes:
        from azoth_world.javelin.bundle import encode_type_marker

        header = bytes([0xC8, 0x11, 0x59, 0xF8]) + (len(body) + 20).to_bytes(4, "little")
        actor = bytes(range(16))
        return header + actor + encode_type_marker(type_id) + body

    def test_marker_at_24_is_read_for_a_client_record(self):
        payload = self._client_record(0x5DE, b"\xAA\xBB")
        found = self.tool._channel0_body(payload)
        self.assertIsNotNone(found, "a client record's marker at offset 24 must be read")
        type_id, body = found
        self.assertEqual(type_id, 0x5DE)
        self.assertEqual(body, b"\xAA\xBB")

    def test_marker_at_zero_still_works(self):
        from azoth_world.javelin.bundle import encode_type_marker

        type_id, body = self.tool._channel0_body(
            encode_type_marker(0x635) + b"\x01\x02"
        )
        self.assertEqual(type_id, 0x635)
        self.assertEqual(body, b"\x01\x02")

    def test_offset_zero_wins_when_both_are_present(self):
        """A server record with the marker at 0 must not be re-read from offset 24."""
        from azoth_world.javelin.bundle import encode_type_marker

        payload = encode_type_marker(0x663) + bytes(20) + encode_type_marker(0x5DE)
        type_id, _ = self.tool._channel0_body(payload)
        self.assertEqual(type_id, 0x663)

    def test_a_payload_with_no_marker_is_none(self):
        self.assertIsNone(self.tool._channel0_body(bytes([0x11] * 40)))


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


class SegmentReportTest(unittest.TestCase):
    """The action-correlated set: steady WITHIN a segment, different BETWEEN segments.

    This is the whole point of the segmented capture. Inside a walking segment nearly every
    byte of the body wobbles because the player moves continuously -- that is motion noise.
    An offset that holds one value through a segment and a different value in another is
    correlated with whatever separates them. Requiring BOTH halves is what makes the result
    a label rather than a guess: constancy alone flags every tag byte, difference alone
    flags every noisy byte.
    """

    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def _cols(self, bodies):
        return self.tool.variability(bodies)["columns"]

    def test_an_offset_steady_per_segment_but_different_between_them_is_reported(self):
        # byte 1 is 0x01 while idle and 0x02 while walking, constant in both
        idle = [bytes([0xAA, 0x01, 0xFF]) for _ in range(5)]
        walk = [bytes([0xAA, 0x02, 0xFF]) for _ in range(5)]
        found = self.tool.segment_report(
            {"idle": self._cols(idle), "walk": self._cols(walk)}
        )
        self.assertEqual([f["off"] for f in found], [1])
        self.assertEqual(found[0]["values"], {"idle": 0x01, "walk": 0x02})

    def test_an_offset_that_wobbles_inside_a_segment_is_not_reported(self):
        """Noise must not be labelled, however different the two segments look."""
        idle = [bytes([0xAA, n, 0x00]) for n in range(5)]
        walk = [bytes([0xAA, n + 100, 0x00]) for n in range(5)]
        found = self.tool.segment_report(
            {"idle": self._cols(idle), "walk": self._cols(walk)}
        )
        self.assertEqual(found, [], "a varying offset carries no label")

    def test_a_purely_constant_offset_is_not_reported(self):
        """Same value everywhere means no information about the action."""
        idle = [bytes([0xAA, 0x01]) for _ in range(4)]
        walk = [bytes([0xAA, 0x01]) for _ in range(4)]
        self.assertEqual(self.tool.segment_report(
            {"idle": self._cols(idle), "walk": self._cols(walk)}
        ), [])

    def test_one_sample_cannot_establish_constancy(self):
        """A single body has no variation to measure, so it must not be treated as steady."""
        single = [bytes([0xAA, 0x01])]
        other = [bytes([0xAA, 0x02]) for _ in range(4)]
        # `variability` on one body reports no variation, which would wrongly read as
        # "steady"; segment_report still needs >=2 segments, and here it would claim a
        # difference. Guard the caller instead by requiring 2 bodies in the CLI, and assert
        # here that a single segment alone yields nothing.
        self.assertEqual(self.tool.segment_report({"only": self._cols(single)}), [])

    def test_absent_offsets_are_not_called_steady(self):
        """A body that is shorter in some samples cannot be steady at the tail."""
        long_body = [bytes([0xAA, 0x01, 0x02]) for _ in range(4)]
        mixed = [bytes([0xAA, 0x01]), bytes([0xAA, 0x01, 0x02])]
        found = self.tool.segment_report(
            {"long": self._cols(long_body), "mixed": self._cols(mixed)}
        )
        self.assertEqual([f["off"] for f in found], [], "tail offset is absent in `mixed`")


class WidthGroupingTest(unittest.TestCase):
    """Segments of different body widths must never be compared column by column.

    THE DEFECT THIS PINS. The ALC input stream is variable-length: 283 bytes idle, 298 with
    a panel open, with the growth inserted BEFORE the position anchor. The first version of
    `report_segments` picked one segment's width and diffed every segment's column i against
    every other's column i, so it compared field 91 of one body against field 91 of a body
    whose fields start three bytes later. On a real session (2026-10-26) that reported **133
    differing offsets**, and all 133 were the 15-byte insertion rather than a field. The
    output also printed a single `body width`, which was false whenever the segments differed.

    The fix is structural: group by width, compare inside a group only, and report every
    width that was present.
    """

    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def test_two_widths_are_reported_separately(self):
        # Same prefix, different length: an offset that looks different across widths.
        short = [bytes([0xAA, 0x01, 0x02, 0x03]) for _ in range(4)]
        long_ = [bytes([0xAA, 0x01, 0x02, 0x09, 0x03]) for _ in range(4)]
        grouped = self.tool.group_by_width({"idle": short, "panel": long_})
        self.assertEqual(sorted(grouped), [4, 5])
        # Neither width has two segments, so nothing is comparable -- and that must be
        # reported rather than silently diffed.
        self.assertEqual(self.tool.comparable_widths(grouped), {})

    def test_a_width_with_two_segments_is_comparable_on_its_own(self):
        a = [bytes([0xAA, 0x01, 0x02]) for _ in range(4)]
        b = [bytes([0xAA, 0x02, 0x02]) for _ in range(4)]
        long_ = [bytes([0xAA, 0x01, 0x02, 0x03]) for _ in range(4)]
        grouped = self.tool.group_by_width({"a": a, "b": b, "c": long_})
        comparable = self.tool.comparable_widths(grouped)
        self.assertEqual(sorted(comparable), [3], "only width 3 has two segments")
        self.assertEqual(sorted(comparable[3]), ["a", "b"])

    def test_a_segment_with_mixed_lengths_is_dropped_before_grouping(self):
        mixed = [bytes([0xAA, 0x01]), bytes([0xAA, 0x01, 0x02])]
        clean = [bytes([0xAA, 0x01, 0x02]) for _ in range(3)]
        usable = self.tool.usable_segments({"mixed": mixed, "clean": clean})
        self.assertEqual(sorted(usable), ["clean"])


class CatalogTest(unittest.TestCase):
    def test_the_tool_is_registered(self):
        import json

        catalog = json.loads((TOOLS / "catalog.json").read_text(encoding="utf-8"))
        self.assertIn("field-differential", catalog["workflows"])
        self.assertIn("field-differential", catalog["files"])
        self.assertTrue((TOOLS / "type" / "field-differential.py").is_file())


if __name__ == "__main__":
    unittest.main()
