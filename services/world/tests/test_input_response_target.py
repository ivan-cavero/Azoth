"""Tests for re-addressing the captured ALC/time-sync replies.

WHY. The red HUD cable is the ALC's `javelin.alc-server-timeout-for-input`: the client streams
its input (`0x635`, ~20/s) and waits for the server to answer. The capture shows the real server
answering immediately with `0x1096`/`0x1097` (`TimeComponentClientFacet_SyncTimeChange` /
`SyncDayPhase`), and those bodies carry a **16-byte target** at offset 4:

    00 01 <type varint> <16-byte target> <payload>

Our replay sends those bodies verbatim, and the client rejects them because that target is the
CAPTURE session's local id for its `TimeComponentClientFacet`; the registry assigns local ids per
session, so our session has a different one. `retarget_typed_body` is what lets the server swap in
the id our client actually has, discovered live by
`reverse/probes/client/facet-target-id` (probe `frida-facet-target-id`).

These tests pin the offset rule and the fail-closed behaviour, so a body that does not look like
that shape is left untouched rather than corrupted.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azoth_world.javelin.replay_store import ReplayStore
from azoth_world.javelin.varint import encode as encode_varint
from azoth_world.rep import client_container, retarget_typed_body, wrap_reply

REPLAY = ROOT / "replay" / "messages-redacted.txt"

# The capture's own target for the two time-sync messages, read from the file.
CAPTURED_TARGET = bytes.fromhex("93a3e477cb5fd51ebf85314bbc4a951a")
NEW_TARGET = bytes.fromhex("00112233445566778899aabbccddeeff")


class TestRetargetTypedBody(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReplayStore(REPLAY)

    def test_target_sits_at_offset_four(self) -> None:
        for seq in (0x75, 0x76):  # 0x1096 and 0x1097
            msg = self.store.get(seq)
            self.assertIsNotNone(msg)
            assert msg is not None
            self.assertEqual(msg.body[4:20], CAPTURED_TARGET, f"seq {seq:#x}")

    def test_rewrites_only_the_target(self) -> None:
        for seq in (0x75, 0x76):
            msg = self.store.get(seq)
            assert msg is not None
            out = retarget_typed_body(msg.body, NEW_TARGET)
            self.assertIsNotNone(out)
            assert out is not None
            self.assertEqual(len(out), len(msg.body), "length must not change")
            self.assertEqual(out[:4], msg.body[:4], "marker and type must not change")
            self.assertEqual(out[4:20], NEW_TARGET)
            self.assertEqual(out[20:], msg.body[20:], "payload must not change")

    def test_captured_target_is_a_no_op(self) -> None:
        msg = self.store.get(0x75)
        assert msg is not None
        self.assertEqual(retarget_typed_body(msg.body, CAPTURED_TARGET), msg.body)

    def test_fails_closed(self) -> None:
        msg = self.store.get(0x75)
        assert msg is not None
        # wrong target width
        self.assertIsNone(retarget_typed_body(msg.body, b"\x00" * 15))
        self.assertIsNone(retarget_typed_body(msg.body, b"\x00" * 17))
        # not a typed body at all
        self.assertIsNone(retarget_typed_body(b"\xff\xff\xff\xff" + msg.body[4:], NEW_TARGET))
        # truncated before the target ends
        self.assertIsNone(retarget_typed_body(msg.body[:18], NEW_TARGET))


class TestClientContainerForm(unittest.TestCase):
    """The channel-1 form: `[u32 BE crc32][u32 BE len][16-byte target][00 01][type][body]`.

    The client's own channel-1 records use this shape (measured 9997/9997 in one
    session, flags 0x20). The capture's server->client form puts the target AFTER the
    typed marker instead, so the two are not interchangeable and the order matters.
    """

    def setUp(self) -> None:
        self.store = ReplayStore(REPLAY)

    def test_crc_and_length_are_correct(self) -> None:
        import zlib

        msg = self.store.get(0x75)  # 0x1096
        assert msg is not None
        payload = msg.body[20:]  # body is `00 01 96 42 <target16> <payload>`
        framed = wrap_reply("client", NEW_TARGET, 0x1096, payload)
        type_varint = encode_varint(0x1096)
        self.assertEqual(len(type_varint), 2, "0x1096 is a two-byte prefix varint")
        self.assertEqual(len(framed), 8 + 16 + 2 + len(type_varint) + len(payload))
        crc = int.from_bytes(framed[:4], "big")
        length = int.from_bytes(framed[4:8], "big")
        inner = framed[8:]
        self.assertEqual(length, len(inner))
        self.assertEqual(crc, zlib.crc32(inner) & 0xFFFFFFFF)
        self.assertEqual(framed[8:24], NEW_TARGET, "target comes first, like the client")
        self.assertEqual(framed[24:26], bytes((0, 1)))
        self.assertEqual(framed[26:28], type_varint)

    def test_matches_the_client_container_helper(self) -> None:
        payload = bytes((0, 0, 0, 2))
        framed = wrap_reply("client", NEW_TARGET, 0x1097, payload)
        inner = NEW_TARGET + bytes((0, 1)) + encode_varint(0x1097) + payload
        self.assertEqual(framed, client_container(inner))


if __name__ == "__main__":
    unittest.main()
