"""Tests for the channel-1 input reader (`javelin.alc`).

The fixtures are REAL payloads lifted from the world server's own traffic log
(`services/world/rep_traffic.jsonl`, the 2026-10-14 sessions), so these tests fail if the
derived layout stops matching the wire rather than if the code stops matching itself.

The three fixtures are chosen to be discriminating:

* ``PRELOAD_154`` — a body from before the player entity exists. It has NO position marker,
  which is the load signal.
* ``LOADED_311`` — the dominant loaded form. Marker at body offset 91.
* ``LOADED_313`` — a loaded form two bytes longer, where the SAME position block sits at
  body offset 93. This is why a fixed offset is wrong and the marker is the locator: a
  reader hard-coded to 103 would report garbage on this payload.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from azoth_world.javelin import alc  # noqa: E402

ACTOR_ID = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")

# 154 bytes, before the player entity exists. No `3d 4c cc cd` marker anywhere.
PRELOAD_154 = bytes.fromhex(
    "3283ca4d000000921a954abc4b3185bfbe37c3d8592618e00001b518fbde4b9a600d428fbf85314bbc4a951a"
    "0001000000000000018502000000000000001f01200d1438000000a31c1105050000006bc080200100808080"
    "800300000001000000006a0080808080030000000100000000690080808080030000000100000000680080"
    "8080800300000001000000006700808080800300000001"
)

# 311 bytes, the dominant loaded form. Marker at body offset 91, position at 103.
LOADED_311 = bytes.fromhex(
    "c29cda180000012f1a954abc4b3185bfbe37c3d8592618e00001b518fbde4b9a600d428fbf85314bbc4a951a"
    "00000000001d0000018e5effffffffffffffff0120090f4400000090043205f7080061b3e04f40200f0101e5"
    "1300000000000000ff0000000800000204ff000000000000000200808080803d4ccccdc03b8424bc48565d46"
    "11efe9452f4b212b5603000000010100000061b21300000000000000ff0000000800000204ff000000000000"
    "00020080808080030000000100000061b11300000000000000ff0000000800000204ff000000000000000200"
    "80808080030000000100000061b01300000000000000ff0000000800000204ff000000000000000200808080"
    "80030000000100000061af1300000000000000ff0000000800000204ff000000000000000200808080800300"
    "000001"
)

# 313 bytes: the same block two bytes further in, because the body is a variable-length
# sequence. Marker at body offset 93, position at 105.
LOADED_313 = bytes.fromhex(
    "7bbc039e000001311a954abc4b3185bfbe37c3d8592618e00001b518fbde4b9a600d428fbf85314bbc4a951a"
    "00000000bf171d000001c00002ffffffffffffffff01200d0f3a0000009f033205f708000c45e04f40200f01"
    "01061300000000000000ff0000000800000204ff000000000000000200808080803d4ccccdc03043e3be8440"
    "b44611f6d7452e61dd2bc80300000001010000000c441300000000000000ff0000000800000204ff00000000"
    "00000002008080808003000000010000000c431300000000000000ff0000000800000204ff00000000000000"
    "02008080808003000000010000000c421300000000000000ff0000000800000204ff00000000000000020080"
    "80808003000000010000000c411300000000000000ff0000000800000204ff00000000000000020080808080"
    "0300000001"
)


class TestContainer(unittest.TestCase):
    """The `[crc32][len][target][00 01][type][body]` shape."""

    def test_target_is_the_local_actor(self) -> None:
        target, type_id, _body = alc.split_container(LOADED_311)
        self.assertEqual(target, ACTOR_ID)

    def test_type_is_the_input_stream(self) -> None:
        _target, type_id, _body = alc.split_container(LOADED_311)
        self.assertEqual(type_id, alc.INPUT_STREAM_TYPE)
        self.assertEqual(type_id, 0x635)
        # 1589, not 3125: `b5 18` is a PREFIX varint, so the low six bits of the leading
        # byte carry data and the value is (0x18 << 6) | 0x35. Reading it as LEB128 gives
        # 0xC35 and then rejects every real record.
        self.assertEqual(type_id, 1589)

    def test_body_starts_after_the_two_byte_type_varint(self) -> None:
        _t, _type_id, body = alc.split_container(LOADED_311)
        self.assertEqual(len(body), len(LOADED_311) - 28)
        self.assertEqual(body[:4].hex(), "fbde4b9a")

    def test_a_payload_without_the_marker_is_rejected(self) -> None:
        broken = bytearray(LOADED_311)
        broken[alc.CONTAINER_MARKER] = 0xFF
        with self.assertRaises(alc.AlcError):
            alc.split_container(bytes(broken))

    def test_a_truncated_payload_is_rejected(self) -> None:
        with self.assertRaises(alc.AlcError):
            alc.split_container(LOADED_311[:20])


class TestPosition(unittest.TestCase):
    """The marker-located float pair."""

    def test_dominant_form_position(self) -> None:
        claim = alc.read_claim(LOADED_311)
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertAlmostEqual(claim.x, 9339.9775390625, places=4)
        self.assertAlmostEqual(claim.y, 2804.695556640625, places=4)
        self.assertEqual(claim.marker_offset, 91)
        self.assertEqual(claim.body_length, 283)

    def test_the_block_moves_with_the_body_length(self) -> None:
        """The discriminating case: a fixed offset of 103 would read the wrong bytes here."""
        claim = alc.read_claim(LOADED_313)
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.marker_offset, 93)
        self.assertAlmostEqual(claim.x, 9341.7099609375, places=4)
        self.assertAlmostEqual(claim.y, 2790.116455078125, places=4)

    def test_preload_body_has_no_position(self) -> None:
        self.assertIsNone(alc.read_claim(PRELOAD_154))

    def test_preload_body_has_no_marker(self) -> None:
        _t, _type_id, body = alc.split_container(PRELOAD_154)
        self.assertNotIn(alc.POSITION_MARKER, body)

    def test_an_ambiguous_body_is_not_guessed(self) -> None:
        """Two markers means the layout changed; picking one would invent a position."""
        _t, _type_id, body = alc.split_container(LOADED_311)
        doubled = body + body[body.find(alc.POSITION_MARKER):]
        self.assertIsNone(alc.read_position(doubled))

    def test_an_implausible_value_is_rejected(self) -> None:
        _t, _type_id, body = alc.split_container(LOADED_311)
        marker = body.find(alc.POSITION_MARKER)
        poisoned = bytearray(body)
        # 1e30 does not fit the plausible world range.
        poisoned[marker + 12:marker + 16] = bytes.fromhex("7149f2ca")
        self.assertIsNone(alc.read_position(bytes(poisoned)))

    def test_distance_is_planar(self) -> None:
        claim = alc.read_claim(LOADED_311)
        assert claim is not None
        self.assertAlmostEqual(claim.distance_to(claim.x, claim.y), 0.0, places=6)
        self.assertAlmostEqual(claim.distance_to(claim.x + 3.0, claim.y + 4.0), 5.0, places=4)


class TestLoadSignal(unittest.TestCase):
    """The marker's presence IS the "player is in the world" signal."""

    def test_preload_is_not_ready(self) -> None:
        self.assertFalse(alc.is_world_ready(PRELOAD_154))

    def test_loaded_is_ready(self) -> None:
        self.assertTrue(alc.is_world_ready(LOADED_311))
        self.assertTrue(alc.is_world_ready(LOADED_313))

    def test_a_foreign_record_is_not_a_claim(self) -> None:
        """Channel 1 also carries system records; they must be skipped, not misread."""
        self.assertIsNone(alc.read_claim(b"\x00\x01\x02\x03"))
        self.assertFalse(alc.is_world_ready(b""))


if __name__ == "__main__":
    unittest.main()


class TestMovementBlock(unittest.TestCase):
    """The client's own movement state, decoded from its input stream.

    MEASURED 2026-10-18 over 34 distinct positions in one session: the block at body offset 119
    (marker `3d4ccccd` = 0.05) carries `a`, `b`, `x`, `y` as big-endian float32, and `x`,`y` equal
    the pair the position claim reports **34 of 34** times to within 0.01 u. Validated again through
    the reader over 201 samples with 0 mismatches.

    `a` and `b` vary with movement but their meaning is NOT established, so they are exposed raw.
    """

    # A real 311-byte payload whose claim is (9339.9775, 2804.6956).
    PAYLOAD = bytes.fromhex(
        "571b62aa0000012f1a954abc4b3185bfbe37c3d8592618e00001b518fbde4b9a600d428fbf85314bbc4a951a"
        "00000000001e000001a572ffffffffffffffff0120090f45000000a1033705f70800772de04f40200f0100"
        "571300000000000000ff0000000800000204ff000000000000000200808080803d4ccccdc03b8424bc48565d"
        "4611efe9452f4b212b5603000000010100000075e11300000000000000ff0000000800000204ff0000000000"
        "0000020080808080030000000100000075e01300000000000000ff0000000800000204ff0000000000000002"
        "0080808080030000000100000075df1300000000000000ff0000000800000204ff0000000000000002008080"
        "8080030000000100000075de1300000000000000ff0000000800000204ff0000000000000002008080808003"
        "00000001"
    )

    def test_the_marker_is_where_the_measurement_put_it(self) -> None:
        """Both offsets, because mixing payload and body offsets is an easy mistake.

        The measurement was taken on the PAYLOAD (119); the reader works on the BODY, which starts
        28 bytes later, so the same marker is at body offset 91.
        """
        _t, _ty, body = alc.split_container(self.PAYLOAD)
        self.assertEqual(self.PAYLOAD.find(alc.MOVEMENT_MARKER), alc.MOVEMENT_BLOCK_OFFSET)
        self.assertEqual(alc.MOVEMENT_BLOCK_OFFSET, 119)
        self.assertEqual(body.find(alc.MOVEMENT_MARKER), alc.MOVEMENT_BLOCK_BODY_OFFSET)
        self.assertEqual(alc.MOVEMENT_BLOCK_BODY_OFFSET, 91)

    def test_the_block_carries_the_position(self) -> None:
        mv = alc.read_movement_from_payload(self.PAYLOAD)
        self.assertIsNotNone(mv)
        assert mv is not None
        self.assertAlmostEqual(mv.x, 9339.9775390625, places=3)
        self.assertAlmostEqual(mv.y, 2804.695556640625, places=3)

    def test_it_agrees_with_the_position_claim(self) -> None:
        """The measured invariant: 34/34 and 201/201, to within 0.01 u."""
        claim = alc.read_claim(self.PAYLOAD)
        mv = alc.read_movement_from_payload(self.PAYLOAD)
        assert claim is not None and mv is not None
        self.assertAlmostEqual(mv.x, claim.x, places=2)
        self.assertAlmostEqual(mv.y, claim.y, places=2)

    def test_a_and_b_are_exposed_raw_not_named(self) -> None:
        """Nothing establishes what they mean, so the reader must not pretend to a velocity."""
        mv = alc.read_movement_from_payload(self.PAYLOAD)
        assert mv is not None
        self.assertIsInstance(mv.a, float)
        self.assertIsInstance(mv.b, float)
        # They are the two floats before x; a test pins the offsets so a layout drift is visible.
        self.assertEqual(alc.MOVEMENT_A_OFFSET, 4)
        self.assertEqual(alc.MOVEMENT_B_OFFSET, 8)
        self.assertEqual(alc.MOVEMENT_X_OFFSET, 12)

    def test_a_preload_body_has_no_movement_block(self) -> None:
        self.assertIsNone(alc.read_movement_from_payload(PRELOAD_154))

    def test_a_body_without_the_marker_is_not_guessed(self) -> None:
        self.assertIsNone(alc.read_movement_state(b"\x00" * 200))


class TestCameraYaw(unittest.TestCase):
    """`a` is the camera yaw, established by the distribution of movement against it.

    MEASURED 2026-10-18 over **1008 displacements** in six sessions. Classifying each displacement
    by `(movement heading - a)`:

        strafe left  (+90 deg)   47.8%
        back         (+180)      24.4%
        strafe right (-90)       11.8%
        forward      (0)          5.4%

    That is the signature of WASD movement relative to a camera. The competing reading - that `a` is
    the direction of travel - fits only 5.4% and is refuted; it was the first hypothesis and the
    measurement killed it.
    """

    PAYLOAD = TestMovementBlock.PAYLOAD

    def test_a_is_exposed_as_the_camera_yaw(self) -> None:
        mv = alc.read_movement_from_payload(self.PAYLOAD)
        assert mv is not None
        self.assertAlmostEqual(mv.camera_yaw, mv.a, places=9)
        self.assertAlmostEqual(mv.camera_yaw_degrees, -167.87, places=1)

    def test_the_yaw_is_in_radians_within_pi(self) -> None:
        import math

        mv = alc.read_movement_from_payload(self.PAYLOAD)
        assert mv is not None
        self.assertGreaterEqual(mv.camera_yaw, -math.pi)
        self.assertLessEqual(mv.camera_yaw, math.pi)

    def test_the_offset_is_pinned(self) -> None:
        """A layout drift would silently turn the yaw into something else."""
        self.assertEqual(alc.CAMERA_YAW_OFFSET, alc.MOVEMENT_A_OFFSET)
        self.assertEqual(alc.CAMERA_YAW_OFFSET, 4)

    def test_b_is_the_camera_pitch(self) -> None:
        """`b` is the pitch, established the same way as the yaw.

        MEASURED 2026-10-18: `b` changes only 770 times in 197810 samples (mean run 256) - held
        camera state, exactly like the yaw's 729 changes - and spans [-30.3 deg, +26.1 deg], a pitch
        range. **691 of the 808 angle changes are simultaneous in `a` and `b`** (turning the mouse
        diagonally), with 38 yaw-only and 79 pitch-only changes (looking up or down). Its
        correlation against speed, forward speed and lateral speed is under 0.10, which is what an
        independent camera angle looks like.
        """
        mv = alc.read_movement_from_payload(self.PAYLOAD)
        assert mv is not None
        self.assertAlmostEqual(mv.camera_pitch, mv.b, places=9)
        self.assertAlmostEqual(mv.camera_pitch_degrees, -0.70, places=1)

    def test_the_block_is_pitch_yaw_x_y(self) -> None:
        """The four floats are the camera orientation plus the world position, in that order."""
        mv = alc.read_movement_from_payload(self.PAYLOAD)
        assert mv is not None
        self.assertAlmostEqual(mv.camera_pitch, mv.b, places=9)   # offset +4
        self.assertAlmostEqual(mv.camera_yaw, mv.a, places=9)     # offset +8
        self.assertAlmostEqual(mv.x, 9339.9775, places=2)         # offset +12
        self.assertAlmostEqual(mv.y, 2804.6956, places=2)         # offset +16

    def test_no_velocity_is_invented(self) -> None:
        mv = alc.read_movement_from_payload(self.PAYLOAD)
        assert mv is not None
        self.assertFalse(hasattr(mv, "speed"))
        self.assertFalse(hasattr(mv, "heading"))


class TestMovementBuffer(unittest.TestCase):
    """The LIVE position feed: a sliding buffer of recent movement samples.

    WHY THIS CLASS EXISTS, and the mistake it records: the idle channel-1 body is **311 bytes** and
    carries ONE position - the spawn anchor, which does not move. Everything in this project filtered
    for `len(payload) == 311`, so the anchor was all it ever saw, and it concluded the channel carried
    no live position. **It does.** When the player moves the body grows to ~409 bytes and carries the
    last five movement samples, newest first.

    MEASURED 2026-10-18 against the client's own position accessor polled at 20 Hz during a real
    23 u walk: **600 of 600 buffer entries landed on the accessor's trajectory** within 0.5 u, across
    120 messages, entry by entry. Entries are 0.051 s apart (20 Hz).
    """

    # A real 409-byte payload captured while the player walked. Five entries, newest first.
    MOVING = bytes.fromhex(
        "fbde4b9a600d428fbf85314bbc4a951a00000000001e000001b709ffffffffffffffff01200c103c000000"
        "aa023d05f7080008aee04f40200f01013c13fc0020000000040000000000f000000020ff000000080000"
        "0204ff000000400000000200808080803d4ccccdc02c107e800000004612030f452df46c2c0d0300000001"
        "0190000008ad012413fc0020000000040000000000f000000020ff0000000800000204ff00000040000000"
        "0200808080804612026b452df9b12c0d030000000190000008ac012413fc0020000000040000000000f000"
        "000020ff0000000800000204ff0000004000000002008080808046120219452dfc542c0d03000000019000"
        "0008ab012413fc0020000000040000000000f000000020ff0000000800000204ff00000040000000020080"
        "80808046120175452e01992c0c030000000190000008aa012413fc0020000000040000000000f000000020"
        "ff0000000800000204ff0000004000000002008080808046120123452e043c2c0c0300000001"
    )

    def test_it_returns_five_entries_newest_first(self) -> None:
        buf = alc.read_movement_buffer(self.MOVING)
        self.assertEqual(len(buf), 5)
        # Newest first: the first entry is furthest along the walk.
        self.assertAlmostEqual(buf[0][0], 9344.7646, places=3)
        self.assertAlmostEqual(buf[0][1], 2783.2764, places=3)
        self.assertAlmostEqual(buf[4][0], 9344.2842, places=3)
        self.assertAlmostEqual(buf[4][1], 2784.2646, places=3)

    def test_the_entries_are_consecutive_samples(self) -> None:
        """A movement buffer's entries must be close together: ~0.2 u apart at 20 Hz."""
        import math

        buf = alc.read_movement_buffer(self.MOVING)
        for a, b in zip(buf, buf[1:]):
            step = math.hypot(b[0] - a[0], b[1] - a[1])
            self.assertLess(step, 1.0, "consecutive samples must be close")
            self.assertGreater(step, 0.0, "they must actually differ")

    def test_the_idle_form_returns_one_entry(self) -> None:
        """311 bytes = the anchor alone. Same head, fewer entries."""
        idle = alc.read_movement_buffer_from_payload(TestMovementBlock.PAYLOAD)
        self.assertEqual(len(idle), 1)

    def test_the_live_position_is_the_newest_entry(self) -> None:
        live = alc.read_movement_buffer(self.MOVING)[0]
        self.assertEqual(alc.read_live_position(
            bytes.fromhex("00000000") + b"\x00" * 24 + self.MOVING), None,
            "a body with no container is not a live position")
        # On a real payload the live position is the buffer's head.
        self.assertEqual(live, alc.read_movement_buffer(self.MOVING)[0])

    def test_a_body_without_the_marker_has_no_buffer(self) -> None:
        self.assertEqual(alc.read_movement_buffer(b"\x00" * 400), ())

    def test_the_frame_offset_is_the_measured_one(self) -> None:
        """wire = accessor + offset, constant to 0.000 u. The server stays in the wire frame."""
        self.assertAlmostEqual(alc.MOVEMENT_FRAME_OFFSET[0], -2.2002, places=4)
        self.assertAlmostEqual(alc.MOVEMENT_FRAME_OFFSET[1], 3.3777, places=4)
        # The anchor in the wire frame converts back to the accessor value at capture time.
        anchor = (9341.4414, 2790.1104)
        ax, ay = alc.to_accessor_frame(anchor)
        self.assertAlmostEqual(ax, 9343.6416, places=2)
        self.assertAlmostEqual(ay, 2786.7327, places=2)
