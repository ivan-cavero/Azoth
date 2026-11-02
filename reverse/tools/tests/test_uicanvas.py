"""LyShine UI canvas (AZ ObjectStream) tests (stdlib unittest).

The canvas container is AZ ObjectStream, the public O3DE binary serialization
format (`Code/Framework/AzCore/AzCore/Serialization/ObjectStream.cpp`). These
tests pin the element grammar against a synthetic stream, so the reader/writer
can be trusted without the 71 GB client install. One integration test parses a
real canvas when the install and index are present, and is skipped otherwise.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uicanvas  # noqa: E402

ROOT_UUID = uuid.UUID("75651658-8663-478D-9090-2432DFCAFA44")


def synthetic_stream() -> bytes:
    """A minimal, valid ObjectStream: header + one aggregate root with two leaves."""
    out = bytearray([0])                       # s_binaryStreamTag
    out += (3).to_bytes(4, "big")              # s_objectStreamVersion (endian-swapped on write)

    # Root: element header + has version, no name, no value -> aggregate.
    out += bytes([uicanvas.FLAG_HAS_VERSION | uicanvas.FLAG_ELEMENT_HEADER])
    out += bytes([2])                          # element version
    out += ROOT_UUID.bytes                     # 16 raw bytes

    # Leaf 1: named, value inline in the flags (size 4).
    out += bytes([
        uicanvas.FLAG_HAS_NAME | uicanvas.FLAG_HAS_VALUE
        | uicanvas.FLAG_ELEMENT_HEADER | 4
    ])
    out += (0xDEADBEEF).to_bytes(4, "big")     # nameCrc
    out += bytes(range(16))                    # element uuid
    out += bytes([1, 2, 3, 4])                 # value
    out += bytes([uicanvas.FLAG_ELEMENT_END])  # the leaf's own close tag

    # Leaf 2: value behind an extra size field (width 2 -> 300 bytes).
    out += bytes([
        uicanvas.FLAG_HAS_VALUE | uicanvas.FLAG_EXTRA_SIZE_FIELD
        | uicanvas.FLAG_ELEMENT_HEADER | 2
    ])
    out += bytes(range(16, 32))                # element uuid
    out += (300).to_bytes(2, "big")
    out += bytes([9]) * 300
    out += bytes([uicanvas.FLAG_ELEMENT_END])  # the leaf's own close tag

    out += bytes([uicanvas.FLAG_ELEMENT_END])  # closes the root
    out += bytes([uicanvas.FLAG_ELEMENT_END])  # the stream terminator
    return bytes(out)


class RoundTripTest(unittest.TestCase):
    def test_synthetic_round_trips_byte_exact(self) -> None:
        data = synthetic_stream()
        self.assertEqual(uicanvas.serialize(uicanvas.parse(data)), data)

    def test_header_version_is_read(self) -> None:
        ir = uicanvas.parse(synthetic_stream())
        self.assertEqual(ir["stream_version"], 3)
        self.assertEqual(ir["root"]["type_id"], ROOT_UUID)

    def test_element_tree_shape(self) -> None:
        ir = uicanvas.parse(synthetic_stream())
        root = ir["root"]
        self.assertIsNone(root["value"])
        self.assertEqual(len(root["children"]), 2)
        leaf1, leaf2 = root["children"]
        self.assertEqual(leaf1["name_crc"], 0xDEADBEEF)
        self.assertEqual(leaf1["value"], bytes([1, 2, 3, 4]))
        self.assertEqual(len(leaf2["value"]), 300)
        self.assertEqual(uicanvas.count_elements(ir), 3)

    def test_inline_size_leaf_without_name(self) -> None:
        # A leaf with a 3-byte inline value and no name/version, under a root.
        data = bytearray([0]) + (3).to_bytes(4, "big")
        data += bytes([uicanvas.FLAG_HAS_VERSION | uicanvas.FLAG_ELEMENT_HEADER, 2])
        data += ROOT_UUID.bytes
        data += bytes([uicanvas.FLAG_HAS_VALUE | uicanvas.FLAG_ELEMENT_HEADER | 3])
        data += bytes(range(16))            # element uuid
        data += bytes([0xAA, 0xBB, 0xCC])
        data += bytes([uicanvas.FLAG_ELEMENT_END])  # the leaf's own close tag
        data += bytes([uicanvas.FLAG_ELEMENT_END])  # the root's close tag
        data += bytes([uicanvas.FLAG_ELEMENT_END])  # the stream terminator
        data = bytes(data)
        ir = uicanvas.parse(data)
        self.assertEqual(ir["root"]["children"][0]["value"], bytes([0xAA, 0xBB, 0xCC]))
        self.assertEqual(uicanvas.serialize(ir), data)


class ValueSizeEncodingTest(unittest.TestCase):
    """The value-size encoding is recomputed from the actual value length.

    An edit can change a value's length, so the stored flags byte (inline size
    or EXTRA_SIZE_FIELD width) must be derived from `len(value)`: inline when
    < 8, else the extra size field with width 1/2/4. Name/version/type bits are
    kept. An unedited canvas still recomputes to the same byte, so it stays
    byte-exact.
    """

    def test_inline_size_recomputed_from_length(self) -> None:
        flags, prefix = uicanvas.value_size_encoding(
            uicanvas.FLAG_HAS_VALUE | uicanvas.FLAG_HAS_NAME | 3, 5)
        self.assertFalse(flags & uicanvas.FLAG_EXTRA_SIZE_FIELD)
        self.assertEqual(flags & uicanvas.VALUE_SIZE_MASK, 5)
        self.assertTrue(flags & uicanvas.FLAG_HAS_NAME)
        self.assertEqual(prefix, b"")

    def test_growing_past_inline_switches_to_extra_size_field(self) -> None:
        flags, prefix = uicanvas.value_size_encoding(
            uicanvas.FLAG_HAS_VALUE | uicanvas.FLAG_HAS_NAME | 3, 10)
        self.assertTrue(flags & uicanvas.FLAG_EXTRA_SIZE_FIELD)
        self.assertEqual(flags & uicanvas.VALUE_SIZE_MASK, 1)
        self.assertTrue(flags & uicanvas.FLAG_HAS_NAME)
        self.assertEqual(prefix, (10).to_bytes(1, "big"))

    def test_width_widens_for_large_values(self) -> None:
        for length, width in ((300, 2), (70000, 4)):
            flags, prefix = uicanvas.value_size_encoding(
                uicanvas.FLAG_HAS_VALUE | uicanvas.FLAG_HAS_VERSION | 4, length)
            self.assertTrue(flags & uicanvas.FLAG_EXTRA_SIZE_FIELD)
            self.assertEqual(flags & uicanvas.VALUE_SIZE_MASK, width)
            self.assertTrue(flags & uicanvas.FLAG_HAS_VERSION)
            self.assertEqual(prefix, length.to_bytes(width, "big"))

    def test_length_changing_edit_re_parses(self) -> None:
        ir = uicanvas.parse(synthetic_stream())
        leaf = ir["root"]["children"][0]
        self.assertEqual(len(leaf["value"]), 4)
        leaf["value"] = b"0123456789"  # 10 bytes: past the 7-byte inline limit
        again = uicanvas.parse(uicanvas.serialize(ir))
        self.assertEqual(again["root"]["children"][0]["value"], b"0123456789")
        # and unedited leaves are untouched
        self.assertEqual(again["root"]["children"][1]["value"], bytes([9]) * 300)


class RejectionTest(unittest.TestCase):
    def test_bad_stream_tag_is_rejected(self) -> None:
        data = bytearray(synthetic_stream())
        data[0] = 0x3C  # '<' = XML tag, not binary
        with self.assertRaises(uicanvas.CanvasError):
            uicanvas.parse(bytes(data))

    def test_unsupported_stream_version_is_rejected(self) -> None:
        data = bytearray(synthetic_stream())
        data[1:5] = (99).to_bytes(4, "big")
        with self.assertRaises(uicanvas.CanvasError):
            uicanvas.parse(bytes(data))

    def test_truncated_stream_is_rejected(self) -> None:
        with self.assertRaises(uicanvas.CanvasError):
            uicanvas.parse(synthetic_stream()[:-3])


if __name__ == "__main__":
    unittest.main()
