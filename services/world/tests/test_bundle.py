"""Tests for the Javelin prefix varint and the type-0x08 state bundle.

The fixtures are real bytes from the committed login capture
(`services/world/replay/messages-redacted.txt`), so these tests fail if the
derived layout stops matching the wire — not merely if the code stops matching
itself.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from azoth_world.javelin import bundle, varint  # noqa: E402

CAPTURE = ROOT / "replay" / "messages-redacted.txt"

# seq 0xab, 78 bytes: the smallest captured state bundle. Its payload is 66
# bytes and is TWO records of 33 bytes each (`48 03 …` and `49 03 …`), which is
# how the record-sequence model was confirmed byte-exactly.
TINY_BUNDLE = bytes.fromhex(
    "0001080130010101010000424803030c01010804b22d010100000a0102"
    "53ed722b640146c50365f269147861584903030c01010804b22d010100"
    "000a01021bcbd422a956d15c0365f26914786158"
)
# The spawn record: replication seq 1, payload 46393 bytes starting `01 30`,
# i.e. record_id 1 with 48 fragments.
SPAWN_HEAD = bytes.fromhex("0001080101010101010000d9a905")
SPAWN_PAYLOAD_LEN = 46393
SPAWN_PAYLOAD_HEAD = bytes.fromhex("0130")


class TestPrefixVarint(unittest.TestCase):
    """The encoding every typed message and every bundle field starts with."""

    # (encoded, value) pairs read straight out of the capture.
    VECTORS = (
        (bytes.fromhex("08"), 0x08),
        (bytes.fromhex("03"), 0x03),
        (bytes.fromhex("9d05"), 0x15D),
        (bytes.fromhex("886e"), 0x1B88),
        (bytes.fromhex("a319"), 0x663),
        (bytes.fromhex("a05a"), 0x16A0),
        (bytes.fromhex("8a10"), 0x40A),
        (bytes.fromhex("b40a"), 692),
        (bytes.fromhex("d9a905"), 46393),
    )

    def test_capture_vectors_decode(self):
        for raw, expected in self.VECTORS:
            with self.subTest(raw=raw.hex()):
                value, end = varint.decode(raw)
                self.assertEqual(value, expected)
                self.assertEqual(end, len(raw))

    def test_capture_vectors_encode(self):
        for raw, value in self.VECTORS:
            with self.subTest(value=value):
                self.assertEqual(varint.encode(value), raw)

    def test_round_trip_across_every_width_boundary(self):
        boundaries = [
            0,
            0x7F,
            0x80,
            (1 << 14) - 1,
            1 << 14,
            (1 << 21) - 1,
            1 << 21,
            (1 << 28) - 1,
            1 << 28,
            varint.MAX_VALUE,
        ]
        for value in boundaries:
            with self.subTest(value=value):
                encoded = varint.encode(value)
                self.assertEqual(varint.decode(encoded), (value, len(encoded)))
                self.assertEqual(varint.size_of(value), len(encoded))

    def test_widths_grow_by_one_byte_per_continuation(self):
        self.assertEqual(varint.size_of(0x7F), 1)
        self.assertEqual(varint.size_of(0x80), 2)
        self.assertEqual(varint.size_of(1 << 14), 3)
        self.assertEqual(varint.size_of(1 << 21), 4)
        self.assertEqual(varint.size_of(1 << 28), 5)

    def test_continuation_bytes_are_little_endian(self):
        """The 3-byte case is the one Ghidra renders misleadingly.

        Big-endian would make `d9 a9 05` equal 1384633, which is larger than
        the 46407-byte message containing it, so it cannot be the payload
        length. Little-endian gives 46393, which is exactly right.
        """
        self.assertEqual(varint.decode(bytes.fromhex("d9a905"))[0], 46393)
        self.assertNotEqual(varint.decode(bytes.fromhex("d9a905"))[0], 1384633)

    def test_truncated_varint_is_rejected(self):
        with self.assertRaises(varint.VarintError):
            varint.decode(bytes.fromhex("9d"))
        with self.assertRaises(varint.VarintError):
            varint.decode(bytes.fromhex("d9a9"))

    def test_out_of_range_value_is_rejected(self):
        with self.assertRaises(varint.VarintError):
            varint.encode(-1)
        with self.assertRaises(varint.VarintError):
            varint.encode(varint.MAX_VALUE + 1)


class TestTypeMarker(unittest.TestCase):
    """`00 01 <varint type>` — the tag every inbound typed message carries."""

    def test_marker_round_trip(self):
        for type_id in (0x03, 0x08, 0x15D, 0x1B88, 0x16A0, 0x40A):
            with self.subTest(type_id=hex(type_id)):
                body = bundle.encode_type_marker(type_id) + b"payload"
                got, offset = bundle.read_type_marker(body)
                self.assertEqual(got, type_id)
                self.assertEqual(body[offset:], b"payload")

    def test_missing_marker_is_rejected(self):
        with self.assertRaises(bundle.BundleError):
            bundle.read_type_marker(b"\x00\x02\x08")


class TestBundleDecode(unittest.TestCase):
    def test_decodes_a_real_capture_bundle(self):
        parsed = bundle.decode_bundle(TINY_BUNDLE)
        self.assertEqual(parsed.replication_seq, 0x30)
        self.assertEqual(len(parsed.payload), 66)
        self.assertEqual(bundle.encode_type_marker(8) + parsed.encode_body(), TINY_BUNDLE)

    def test_the_payload_is_a_sequence_of_records(self):
        """The finding that corrected the previous model.

        The 78-byte bundle's payload is 66 bytes and the client measured
        `consumed=33, fragments=3` for each of two records, so the payload is
        exactly two 33-byte records: `48 03 …` and `49 03 …`. The old model read
        the whole 66 bytes as ONE fragment's payload, and reported
        `fragment_count = 1`; the real count is 3 per record.
        """
        payload = bundle.decode_bundle(TINY_BUNDLE).payload
        self.assertEqual(len(payload), 66)
        first, second = payload[:33], payload[33:]
        self.assertEqual(first[:2], bytes.fromhex("4803"))  # record_id 0x48, 3 frags
        self.assertEqual(second[:2], bytes.fromhex("4903"))  # record_id 0x49, 3 frags
        # Same fragment shape, different record id; the shared suffix is the
        # trailing key both records end with.
        self.assertEqual(first[-8:], second[-8:])
        self.assertEqual(first[-8:], bytes.fromhex("0365f26914786158"))

    def test_spawn_record_header(self):
        """The spawn record: replication seq 1, 46393-byte payload, `01 30`.

        `01` is record_id 1 (the local-player metadata slot) and `30` is 48
        fragments — the number the live probe measured as nested reader calls.
        """
        body = SPAWN_HEAD + SPAWN_PAYLOAD_HEAD + bytes(SPAWN_PAYLOAD_LEN - 2)
        parsed = bundle.decode_bundle(body)
        self.assertEqual(parsed.replication_seq, 1)
        self.assertEqual(len(parsed.payload), SPAWN_PAYLOAD_LEN)
        self.assertEqual(parsed.payload[:2], SPAWN_PAYLOAD_HEAD)
        self.assertEqual(parsed.payload[1], 48)  # fragment_count
        self.assertEqual(bundle.encode_type_marker(8) + parsed.encode_body(), body)

    def test_trailing_bytes_are_rejected(self):
        with self.assertRaises(bundle.BundleError):
            bundle.decode_bundle(TINY_BUNDLE + b"\x00")

    def test_wrong_type_is_rejected(self):
        with self.assertRaises(bundle.BundleError):
            bundle.decode_bundle(bundle.encode_type_marker(0x1B88) + b"\x00")

    def test_truncated_payload_is_rejected(self):
        with self.assertRaises(bundle.BundleError):
            bundle.decode_bundle(TINY_BUNDLE[:-1])

    def test_a_moved_prologue_tail_is_rejected(self):
        """The six invariant prologue bytes are a layout check.

        If a future build moves them, every offset in bundle.py is suspect and
        the parser must refuse rather than silently misread the payload.
        """
        broken = bytearray(TINY_BUNDLE)
        broken[5] ^= 0xFF  # first byte of the invariant tail
        with self.assertRaises(bundle.BundleError):
            bundle.decode_bundle(bytes(broken))

    def test_looks_like_state_bundle(self):
        self.assertTrue(bundle.looks_like_state_bundle(TINY_BUNDLE))
        self.assertFalse(bundle.looks_like_state_bundle(b"\x00\x01\x9d\x05"))
        self.assertFalse(bundle.looks_like_state_bundle(b""))


class TestFragmentHeader(unittest.TestCase):
    """A fragment is `[varint key][varint type_index][payload]`.

    Measured 2026-10-10 with a live Frida probe (shared varint reader + record
    reader + fragment reader): across 300 fragments the first two varints sit at
    offset 0 and 1 in every single one, with zero exceptions, and there is no
    length field. The fixtures below are the real first bytes of the spawn
    record's fragments, taken from the probe's cursor dumps.
    """

    # (first bytes of the fragment, expected key, expected type, header size)
    VECTORS = (
        (bytes.fromhex("478e4c0301"), 71, 4878, 3),
        (bytes.fromhex("0ab53b01"), 10, 3829, 3),
        (bytes.fromhex("1b810201"), 27, 129, 3),
        (bytes.fromhex("1f871e01"), 31, 1927, 3),
        (bytes.fromhex("2db42d01"), 45, 2932, 3),
        (bytes.fromhex("388b3102"), 56, 3147, 3),
        (bytes.fromhex("0cab1201"), 12, 1195, 3),
        (bytes.fromhex("4c9b1b01"), 76, 1755, 3),
        (bytes.fromhex("43a13901"), 67, 3681, 3),
    )

    def test_real_spawn_fragment_headers(self):
        for raw, key, type_index, size in self.VECTORS:
            with self.subTest(raw=raw.hex()):
                header = bundle.read_fragment_header(raw)
                self.assertEqual(header.key, key)
                self.assertEqual(header.type_index, type_index)
                self.assertEqual(header.header_size, size)

    def test_header_is_two_varints_and_nothing_else(self):
        """The third varint of type 15 needs only one byte, so the header is 2.

        A type below 0x80 encodes to one byte, which is why the header size is
        not a constant -- it is 1 + size_of(type_index).
        """
        header = bundle.read_fragment_header(bytes.fromhex("290f01"))
        self.assertEqual(header.key, 0x29)
        self.assertEqual(header.type_index, 0x0F)
        self.assertEqual(header.header_size, 2)

    def test_a_truncated_header_is_rejected(self):
        with self.assertRaises(bundle.BundleError):
            bundle.read_fragment_header(bytes.fromhex("47"))
        with self.assertRaises(bundle.BundleError):
            bundle.read_fragment_header(bytes.fromhex("478e"))


class TestReplicationSeqRewrite(unittest.TestCase):
    """Advancing the counter the client's replication gate compares.

    The gate drops a bundle whose counter is at or below its high-water, and the
    counter is a varint. Overwriting one raw byte with a value >= 0x80 turns a
    one-byte varint into a two-byte one and shifts everything after it, which is
    the measured `ValidationError`. The rewrite must re-encode.
    """

    def test_rewrite_preserves_the_payload(self):
        parsed = bundle.decode_bundle(TINY_BUNDLE)
        rewritten = bundle.with_replication_seq(TINY_BUNDLE, 0x30 + 1)
        again = bundle.decode_bundle(rewritten)
        self.assertEqual(again.replication_seq, 0x31)
        self.assertEqual(again.payload, parsed.payload)

    def test_rewrite_survives_a_width_change(self):
        """0x35 -> 0x80 widens the varint from one byte to two.

        A raw byte write would corrupt the bundle here; the rebuild must not.
        """
        body = bundle.with_replication_seq(TINY_BUNDLE, 0x35)
        self.assertEqual(varint.size_of(0x35), 1)
        widened = bundle.with_replication_seq(body, 0x80)
        self.assertEqual(varint.size_of(0x80), 2)
        parsed = bundle.decode_bundle(widened)
        self.assertEqual(parsed.replication_seq, 0x80)
        self.assertEqual(
            parsed.payload, bundle.decode_bundle(TINY_BUNDLE).payload
        )
        self.assertEqual(len(widened), len(TINY_BUNDLE) + 1)

    def test_rewrite_rejects_a_non_bundle(self):
        with self.assertRaises(bundle.BundleError):
            bundle.with_replication_seq(b"\x00\x01\x9d\x05\x00", 5)


class TestAgainstTheCommittedCapture(unittest.TestCase):
    """Every captured server->client state bundle must parse exactly."""

    @classmethod
    def setUpClass(cls):
        if not CAPTURE.is_file():
            raise unittest.SkipTest(f"capture missing: {CAPTURE}")
        from azoth_world.javelin.replay_store import ReplayStore

        cls.store = ReplayStore(CAPTURE)

    def test_all_capture_types_decode_with_the_varint(self):
        total = 0
        for message in self.store.messages:
            if message.direction != "R":
                continue
            # seq 0x25 is the first message of its datagram and carries a
            # datagram-level preamble this module does not model.
            if message.seq == 0x25:
                continue
            with self.subTest(seq=hex(message.seq)):
                type_id, _ = bundle.read_type_marker(message.body)
                self.assertEqual(type_id, message.type_id)
            total += 1
        self.assertEqual(total, 137)

    def test_every_capture_state_bundle_parses_exactly(self):
        bundles = [
            m
            for m in self.store.messages
            if m.direction == "R" and m.type_id == bundle.STATE_BUNDLE_TYPE
        ]
        self.assertEqual(len(bundles), 79)
        parsed = 0
        for message in bundles:
            if message.seq == 0x25:
                continue  # datagram-first preamble, see the module docstring
            with self.subTest(seq=hex(message.seq)):
                result = bundle.decode_bundle(message.body)
                self.assertEqual(
                    bundle.encode_type_marker(8) + result.encode_body(),
                    message.body,
                )
                parsed += 1
        self.assertEqual(parsed, 78)

    def test_replication_seq_matches_the_live_high_water(self):
        """Independent corroboration that the seq field is the gate counter.

        Live 2026-10-03 the client logged
        `MayHandleReplicationUnreliable() returning false ... seq 39
        m_lastUnreliableReplicationSeq 53`, i.e. its high-water was 53. The
        capture's replication seqs span exactly 1..53, which is what the gate
        counter would look like over that session.
        """
        seqs = {
            bundle.decode_bundle(m.body).replication_seq
            for m in self.store.messages
            if m.direction == "R" and m.type_id == 8 and m.seq != 0x25
        }
        self.assertEqual(min(seqs), 1)
        self.assertEqual(max(seqs), 53)


if __name__ == "__main__":
    unittest.main()
