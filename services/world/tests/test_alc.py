"""The client's channel-1 ALC input stream: the position the client reports about itself.

MEASURED 2026-10-16. The client sends ~20 channel-1 records a second carrying its own world
position as two big-endian float32 values, and this is the first thing the server can READ
about where the player is. The layout is anchored on a structural constant (`0.05f`, the
client's own movement-quantization value) that occurs EXACTLY ONCE in every body that has a
position, with the pair always 12 bytes after it — both measured over 6 000 live bodies.

The vectors below are real bytes from a live session, not synthesised ones, so a change in
the client's layout fails here rather than silently producing a wrong position.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from azoth_world.javelin import alc  # noqa: E402


def _record(body: bytes, type_id: int = alc.TYPE_ALC_INPUT) -> bytes:
    """Wrap a body in the real container: [crc32][len][16-byte target][00 01][type]."""
    from azoth_world.javelin import varint

    target = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
    inner = b"\x00\x01" + varint.encode(type_id) + body
    return bytes(4) + len(inner).to_bytes(4, "big") + target + inner


# A real 225-byte body from a live session. The body begins with the 16-byte local id of
# the server facet the client is calling (`fbde4b9a600d428f...`, the same value family the
# capture's input-response target uses), and carries the position pair
# `46120c7c 452e46ca` = (9347.1211, 2788.4243) at anchor+12.
LIVE_WITH_POSITION = bytes.fromhex(
    "fbde4b9a600d428fbf85314bbc4a951a00000000003b0000019c02000000000fffffff01200b0e3f"
    "00000098041b05e7080000c5e04f40200f01138002fc000000000004fc000000000004000000fe"
    "00000000000080ff0000000800000204ff00000000000000028008808080803d4ccccd3ff266e6"
    "be930b7046120c7c452e46ca2bc6030000000101e3080000c4c080200000808080800000000000"
    "000000800000000000000000000000174503000000010000000000c3008080808003000000010000"
    "0000c20080808080030000000100000000c100808080800300000001"
)
LIVE_WITH_POSITION_VALUE = (9347.12109375, 2788.42431640625)

# A real 65-byte body from the same session: the short form, which carries NO anchor and
# therefore no position. It must not be guessed at.
LIVE_NO_POSITION = bytes.fromhex(
    "fbde4b9a600d428fbf85314bbc4a951a00010000003c00000101000000000000000001200d123800"
    "0000a51001010500000001c080200100808080800300000001"
)


class TestAlcContainer(unittest.TestCase):
    def test_it_strips_the_container_and_identifies_the_type(self):
        payload = _record(LIVE_WITH_POSITION)
        body = alc.alc_body_from_record(payload)
        self.assertEqual(body, LIVE_WITH_POSITION)

    def test_it_refuses_another_channel_one_type(self):
        """The stream must not be decoded for a record that is not the ALC input."""
        self.assertIsNone(alc.alc_body_from_record(_record(LIVE_WITH_POSITION, type_id=0x634)))

    def test_it_refuses_a_short_or_markerless_record(self):
        self.assertIsNone(alc.alc_body_from_record(b""))
        self.assertIsNone(alc.alc_body_from_record(bytes(20)))
        junk = bytearray(_record(LIVE_WITH_POSITION))
        junk[24:26] = b"\x00\x02"
        self.assertIsNone(alc.alc_body_from_record(bytes(junk)))


class TestAlcPosition(unittest.TestCase):
    def test_the_live_bodies_carry_the_measured_position(self):
        parsed = alc.parse_alc_input(LIVE_WITH_POSITION)
        self.assertEqual(parsed.position, LIVE_WITH_POSITION_VALUE)
        self.assertEqual(parsed.body_length, len(LIVE_WITH_POSITION))
        # The anchor is the quantization constant, and it is the only one in the body.
        self.assertEqual(LIVE_WITH_POSITION.count(alc.QUANTIZATION_ANCHOR), 1)
        # The anchor decodes as a float32, so compare against the same width: 0.05 is not
        # exactly representable in binary32 and an == against the Python double would fail.
        self.assertAlmostEqual(
            struct.unpack(
                ">f", LIVE_WITH_POSITION[parsed.anchor_offset:parsed.anchor_offset + 4]
            )[0],
            alc.QUANTIZATION,
            places=6,
        )

    def test_the_short_form_carries_no_position(self):
        """The 65-byte form has no anchor; the extractor must say so, not invent one."""
        self.assertEqual(LIVE_NO_POSITION.count(alc.QUANTIZATION_ANCHOR), 0)
        parsed = alc.parse_alc_input(LIVE_NO_POSITION)
        self.assertIsNone(parsed.position)
        self.assertEqual(parsed.anchor_offset, -1)

    def test_the_pair_is_always_exactly_twelve_bytes_after_the_anchor(self):
        for body in (LIVE_WITH_POSITION,):
            parsed = alc.parse_alc_input(body)
            at = parsed.anchor_offset + alc.POSITION_OFFSET_FROM_ANCHOR
            self.assertEqual(struct.unpack(">ff", body[at:at + 8]), parsed.position)

    def test_an_out_of_range_pair_is_rejected(self):
        """A coincidental anchor must not produce a plausible-looking lie."""
        body = bytearray(LIVE_WITH_POSITION)
        anchor = body.find(alc.QUANTIZATION_ANCHOR)
        at = anchor + alc.POSITION_OFFSET_FROM_ANCHOR
        body[at:at + 8] = struct.pack(">ff", 12.5, -7.25)
        parsed = alc.parse_alc_input(bytes(body))
        self.assertIsNone(parsed.position)
        self.assertGreaterEqual(parsed.anchor_offset, 0, "the anchor itself is still reported")

    def test_a_truncated_body_after_the_anchor_is_rejected(self):
        body = LIVE_WITH_POSITION[: LIVE_WITH_POSITION.find(alc.QUANTIZATION_ANCHOR) + alc.POSITION_OFFSET_FROM_ANCHOR + 4]
        self.assertIsNone(alc.parse_alc_input(body).position)


if __name__ == "__main__":
    unittest.main()


class TestSessionAlcWiring(unittest.TestCase):
    """The session wiring AROUND the parser, because that is where a real bug lived.

    MEASURED 2026-10-16: `_note_alc_input` logged
    `"speed": round(self.movement.last_speed, 3) if self.movement else None`, and `last_speed` is
    None until the SECOND sample. `round(None, 3)` raised `TypeError`, the exception escaped
    `on_app_data`, the session's feed-error handler DROPPED THE PEER, and the client reported
    `transportError 4` + `Disconnected from REP` ~24 s after spawn - twice in a row, until an A/B
    with the validator disabled survived and the traceback named the line. The FIRST sample of every
    session hit it, so the parser's own tests were all green while the session died.

    These tests feed the real container so the whole path runs, and they assert the FIRST sample is
    safe, which is the case that was broken.
    """

    def _session(self):
        from azoth_world.movement import MovementValidator
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.alc_bodies = 0
        session.alc_position = None
        session.alc_position_at = 0.0
        session.alc_first_at = 0.0
        session.alc_position_log_next_at = 0.0
        # min_dt_s=0 on purpose: this suite tests the WIRING, not the burst rule, and the
        # two calls below happen microseconds apart. The burst/settle rules have their own
        # suite in test_movement.py.
        session.movement = MovementValidator(settle_s=0.0, min_dt_s=0.0)
        session.movement_stats_next_at = 0.0
        session.desync = None
        session.desync_next_at = 0.0
        return session

    def test_the_first_sample_of_a_session_does_not_raise(self):
        """The regression: one sample leaves `last_speed` None and used to raise on round()."""
        from azoth_world.rep import PeerSession

        session = self._session()
        PeerSession._note_alc_input(session, _record(LIVE_WITH_POSITION))
        self.assertEqual(session.alc_bodies, 1)
        self.assertEqual(session.alc_position, LIVE_WITH_POSITION_VALUE)
        # The session must still have its validator and must not have dropped anything.
        self.assertIsNotNone(session.movement)
        self.assertEqual(session.movement.samples, 1)
        self.assertEqual(session.movement.flags, 0)

    def test_back_to_back_samples_do_not_raise_and_do_not_invent_a_speed(self):
        """This suite only checks the WIRING; the speed rules have their own suite.

        Two calls microseconds apart are a burst, so with the real defaults they must NOT produce a
        speed - and, more importantly, must not raise (that is the bug this suite exists for).
        """
        from azoth_world.movement import MovementValidator
        from azoth_world.rep import PeerSession

        session = self._session()
        session.movement = MovementValidator()  # real defaults
        PeerSession._note_alc_input(session, _record(LIVE_WITH_POSITION))
        PeerSession._note_alc_input(session, _record(LIVE_WITH_POSITION))
        self.assertEqual(session.movement.samples, 2)
        self.assertIsNone(session.movement.last_speed)

    def test_a_record_that_is_not_the_alc_input_is_ignored(self):
        from azoth_world.rep import PeerSession

        session = self._session()
        PeerSession._note_alc_input(session, _record(LIVE_WITH_POSITION, type_id=0x634))
        self.assertEqual(session.alc_bodies, 0)
        self.assertEqual(session.movement.samples, 0)

    def test_a_positionless_body_is_counted_but_not_validated(self):
        """The short forms carry no anchor; they must not feed the validator or raise."""
        from azoth_world.rep import PeerSession

        session = self._session()
        PeerSession._note_alc_input(session, _record(LIVE_NO_POSITION))
        self.assertEqual(session.alc_bodies, 1)
        self.assertIsNone(session.alc_position)
        self.assertEqual(session.movement.samples, 0)

    def test_it_works_with_the_validator_disabled(self):
        from azoth_world.rep import PeerSession

        session = self._session()
        session.movement = None
        PeerSession._note_alc_input(session, _record(LIVE_WITH_POSITION))
        self.assertEqual(session.alc_bodies, 1)
        self.assertEqual(session.alc_position, LIVE_WITH_POSITION_VALUE)
