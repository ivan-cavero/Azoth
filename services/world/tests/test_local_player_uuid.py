"""Tests for the targeted local-player UUID substitution.

The client's local-player gate compares the UUID carried by a
PlayerComponentClientFacet record against the character UUID in its local
option store; only a match lets the manager context be set. In the official
capture every player's facet carries that UUID in clear text except the
author's own, which is redacted to zeros. These tests pin the selector rule
that fills exactly that one span and nothing else.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azoth_world.javelin.replay_store import (
    ReplayMessage,
    ReplayStore,
    fill_local_player_uuid,
)

CHARACTER = "11111111-1111-1111-1111-111111111111"
REPLAY = ROOT / "replay" / "messages-redacted.txt"
# The 46 KB state bundles that carry the capture author's own facet record.
LOCAL_PLAYER_SEQS = (
    0x25, 0x2A, 0x2B, 0x2E, 0x2F, 0x30, 0x33, 0x34, 0x35, 0x42, 0x44, 0x47,
    0x48, 0x49, 0x4C, 0x4E, 0x4F, 0x52, 0x55, 0x56, 0x59, 0x5A, 0x5B, 0x66,
    0x6C,
)
# Bundles whose 16-byte span must NOT be touched: the repeated interest=91
# records and the other players' own facets.
UNTOUCHED_SEQS = (0x8C, 0xAE, 0x77, 0x79, 0x7B, 0x80, 0x84)


def _synthetic(body: bytes, spans: list[tuple[int, int]], seq: int = 0x2A) -> ReplayMessage:
    return ReplayMessage(
        seq=seq,
        type_id=0x08,
        direction="R",
        body=body,
        has_redaction=bool(spans),
        redacted_spans=list(spans),
    )


class TestFillLocalPlayerUuid(unittest.TestCase):
    """Selector rule: zero 16-byte span followed by a length-prefixed name."""

    def test_fills_span_before_a_name(self):
        body = b"\xaa" * 8 + b"\x00" * 16 + bytes([3]) + b"Bob"
        msg = _synthetic(body, [(8, 16)])
        out = fill_local_player_uuid(msg, character_id=CHARACTER)
        self.assertEqual(out.body[8:24], bytes.fromhex("11" * 16))
        self.assertEqual(out.body[24:], bytes([3]) + b"Bob")
        self.assertEqual(out.substituted_spans, 1)

    def test_ignores_span_without_a_name(self):
        # 0x18 = 24, and the next bytes are not printable: the bundle's other
        # 16-byte span looks exactly like this.
        body = b"\xaa" * 8 + b"\x00" * 16 + bytes([24]) + b"\xab\xda\x37\xcd"
        msg = _synthetic(body, [(8, 16)])
        self.assertIs(fill_local_player_uuid(msg, character_id=CHARACTER), msg)

    def test_ignores_span_with_a_non_printable_name(self):
        body = b"\xaa" * 8 + b"\x00" * 16 + bytes([3]) + b"\x01\x02\x03"
        msg = _synthetic(body, [(8, 16)])
        self.assertIs(fill_local_player_uuid(msg, character_id=CHARACTER), msg)

    def test_ignores_already_filled_span(self):
        body = b"\xaa" * 8 + b"\x22" * 16 + bytes([3]) + b"Bob"
        msg = _synthetic(body, [(8, 16)])
        self.assertIs(fill_local_player_uuid(msg, character_id=CHARACTER), msg)

    def test_session_selector_uses_the_session_uuid(self):
        body = b"\x00" * 16 + bytes([3]) + b"Bob"
        msg = _synthetic(body, [(0, 16)])
        session = "22222222-2222-2222-2222-222222222222"
        out = fill_local_player_uuid(msg, selector="session", session_uuid=session)
        self.assertEqual(out.body[:16], bytes.fromhex("22" * 16))

    def test_fails_closed(self):
        body = b"\x00" * 16 + bytes([3]) + b"Bob"
        msg = _synthetic(body, [(0, 16)])
        self.assertIs(fill_local_player_uuid(msg, character_id=CHARACTER, selector="x"), msg)
        self.assertIs(fill_local_player_uuid(msg, character_id="nope"), msg)
        self.assertIs(fill_local_player_uuid(msg, character_id=""), msg)
        self.assertIs(fill_local_player_uuid(msg, character_id=CHARACTER, seqs={0x99}), msg)
        self.assertIs(fill_local_player_uuid(msg, character_id=CHARACTER, selector="off"), msg)


@unittest.skipUnless(REPLAY.is_file(), "replay dump not present")
class TestFillLocalPlayerUuidAgainstTheCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = ReplayStore(REPLAY)

    def test_fills_exactly_one_span_per_local_player_bundle(self):
        written = 0
        offsets = set()
        for seq in LOCAL_PLAYER_SEQS:
            msg = self.store.get(seq)
            out = fill_local_player_uuid(msg, character_id=CHARACTER)
            self.assertEqual(out.substituted_spans, 1, f"seq {seq:#x}")
            written += out.substituted_spans
            for offset, length in msg.redacted_spans:
                if length == 16 and out.body[offset : offset + 16] != msg.body[offset : offset + 16]:
                    offsets.add(offset)
        self.assertEqual(written, len(LOCAL_PLAYER_SEQS))
        # The same slot in every bundle (the 0x25 body carries an 18-byte
        # prefix, hence the second offset).
        self.assertEqual(offsets, {0x2E15, 0x2E25})

    def test_leaves_the_interest_and_other_player_bundles_alone(self):
        for seq in UNTOUCHED_SEQS:
            msg = self.store.get(seq)
            out = fill_local_player_uuid(msg, character_id=CHARACTER)
            self.assertEqual(out.substituted_spans, 0, f"seq {seq:#x}")


if __name__ == "__main__":
    unittest.main()
