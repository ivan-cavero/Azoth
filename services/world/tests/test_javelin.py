"""Javelin library tests (stdlib unittest).

The round-trip rule: a parser that cannot reproduce its input byte-for-byte
is wrong. The synthetic V3 body is built from the layout constants in
research/docs/REP-PROTOCOL.md (gap sizes follow from the fixed offsets).
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azoth_world.javelin import (
    BitStream,
    BitStreamError,
    BitStreamWriter,
    CarrierEnvelope,
    MessageFlags,
    MessageRecord,
    MarshalState,
    SystemMessageId,
    marshal_datagram,
    marshal_record,
    parse_datagram,
    parse_envelope,
    parse_v3_request,
    parse_v3_request_lenient,
    parse_v3_request_or_lenient,
    serialize_v3_request,
    v3,
)


def make_v3_body() -> bytes:
    """Synthetic valid 832-byte body: gaps follow from the fixed offsets."""
    msg = v3.V3RegistrationRequest(
        prelude=bytes(range(0x21)),
        build_version="6031",
        unknown_400="400",
        sdk_name="Javelin",
        sdk_version="600415",
        sdk_version_tail=0x18,
        build_flavor="[RETAIL]",
        client_signature="sig:fb79c7c4-1c2b-4c0e-9a33-7a11e6e27eb8",
        client_endpoint="127.0.0.1:23971",
        session_uuid="4760baff-f4af-49ee-8875-3e0103c74b07",
        persona_id="amzn1.developerPersonaId." + "a" * 36,
        platform_app_tag="STEAM_APP_ID.1063730",
        platform_user_id="76561198069524636",
        platform_name_blob="steam|14",
        gaps=[b"\x01" * 4, b"\x02" * 10, b"\x03" * 4, b"\x04" * 4, b"\x05", b"", b"", b"", b"\x09" * 5, b"\x0a" * 31, b"\x0b"],
        unknown_worldid_region=bytes.fromhex("62316130303030302d") + b"\xaa" * 12,
        auth_blob=bytes(0x334 - 0x160),
    )
    body = serialize_v3_request(msg)
    assert len(body) == 832, f"builder broken: {len(body)}B"
    return body


class TestBitStream(unittest.TestCase):
    def test_aligned_roundtrip(self):
        w = BitStreamWriter()
        w.write_u16_be(0xCAFE)
        w.write_u8(0x42)
        w.write_bits(b"hello", 40)
        s = BitStream(w.to_bytes())
        self.assertEqual(s.read_u16_be(), 0xCAFE)
        self.assertEqual(s.read_u8(), 0x42)
        self.assertEqual(s.read_bits(40), b"hello")

    def test_unaligned_bits(self):
        # LSB-first placement: write 5 bits of 0xff, then 5 bits of 0x0f;
        # read them back (output masked to n bits).
        w = BitStreamWriter()
        w.write_bits(b"\xff\x00", 5)
        w.write_bits(b"\x0f", 5)
        s = BitStream(w.to_bytes())
        self.assertEqual(s.read_bits(5), b"\x1f")  # low 5 bits of 0xff
        self.assertEqual(s.read_bits(5), b"\x0f")  # low 5 bits of 0x0f

    def test_write_read_same_value(self):
        # The contract that matters: write value X with n bits, read n bits,
        # get X back (unaligned cursor included).
        w = BitStreamWriter()
        w.write_bits(b"\x0f", 5)
        w.write_bits(b"\xab\xcd", 16)
        s = BitStream(w.to_bytes())
        self.assertEqual(s.read_bits(5), b"\x0f")
        self.assertEqual(s.read_bits(16), b"\xab\xcd")

    def test_overrun_raises(self):
        s = BitStream(b"\x00")
        with self.assertRaises(BitStreamError):
            s.read_bits(9)


class TestEnvelope(unittest.TestCase):
    def test_parse_ok(self):
        env, body = parse_envelope(b"\x80\x01\x00\x2aPAYLOAD")
        self.assertEqual((env.type_byte, env.proto, env.sequence), (0x80, 1, 42))
        self.assertEqual(body, b"PAYLOAD")
        self.assertFalse(env.is_compressed)

    def test_rejects_bad_proto(self):
        with self.assertRaises(ValueError):
            parse_envelope(b"\x80\x02\x00\x00")

    def test_rejects_bad_type(self):
        with self.assertRaises(ValueError):
            parse_envelope(b"\x00\x01\x00\x00")  # bit 7 clear
        with self.assertRaises(ValueError):
            parse_envelope(b"\x82\x01\x00\x00")  # bits 1-6 used


class TestRecords(unittest.TestCase):
    def test_marshal_parse_roundtrip(self):
        recs = [
            MessageRecord(channel=0, payload=b"a" * 10, sequence=1, reliable_sequence=1, reliable=True, connecting=True),
            MessageRecord(channel=3, payload=b"\x01\x00\x00\x00\x01", sequence=1),  # system, id LAST
            MessageRecord(channel=0, payload=b"b" * 5, sequence=2, reliable_sequence=2, reliable=True),
        ]
        wire = marshal_datagram(recs)
        result = parse_datagram(wire)
        self.assertIsNone(result.error)
        self.assertEqual(result.trailing_bits, 0)
        self.assertEqual(len(result.messages), 3)
        # First record: channel written (first), sequence + relSeq present.
        m0 = result.messages[0]
        self.assertEqual((m0.channel, m0.payload, m0.sequence, m0.reliable_sequence), (0, b"a" * 10, 1, 1))
        self.assertTrue(m0.reliable and m0.connecting)
        # Second: same channel => MF_DATA_CHANNEL clear; system id is LAST byte.
        m1 = result.messages[1]
        self.assertEqual(m1.channel, 3)
        self.assertEqual(m1.system_msg_id, SystemMessageId.SM_CONNECT_REQUEST)
        # Third: sequential sequence (2 == 1+1) => field omitted, auto-incremented.
        m2 = result.messages[2]
        self.assertEqual(m2.sequence, 2)
        self.assertEqual(m2.reliable_sequence, 2)
        self.assertTrue(m2.flags & MessageFlags.MF_SEQUENTIAL_ID)

    def test_v3_flags_override_roundtrip(self):
        rec = MessageRecord(
            channel=0,
            payload=b"\x00" * 100,
            flags_override=0xE0,  # DATA_CHANNEL | NO_LENGTH | CONNECTING
        )
        wire = marshal_datagram([rec])
        result = parse_datagram(wire)
        self.assertIsNone(result.error)
        m = result.messages[0]
        self.assertEqual(m.flags, 0xE0)
        self.assertEqual(m.payload, b"\x00" * 100)  # payload = to end of datagram


class TestV3(unittest.TestCase):
    def test_strict_roundtrip_byte_for_byte(self):
        body = make_v3_body()
        msg = parse_v3_request(body)
        self.assertEqual(msg.build_version, "6031")
        self.assertEqual(msg.sdk_name, "Javelin")
        self.assertEqual(msg.build_flavor, "[RETAIL]")
        self.assertEqual(msg.platform_app_tag, "STEAM_APP_ID.1063730")
        self.assertEqual(msg.platform_name_blob, "steam|14")
        self.assertIn("sig:", msg.client_signature)
        # The rule: a parser that cannot reproduce its input is wrong.
        self.assertEqual(serialize_v3_request(msg), body)

    def test_lenient_identity_extraction(self):
        body = make_v3_body()
        msg = parse_v3_request(body)
        got = parse_v3_request_lenient(body)
        self.assertEqual(got.session_uuid, msg.session_uuid)
        self.assertEqual(got.persona_id, msg.persona_id)

    def test_or_lenient_fallback(self):
        body = make_v3_body()
        msg = parse_v3_request_or_lenient(body)
        self.assertTrue(msg.persona_id.startswith("amzn1.developerPersonaId."))

    def test_response_88_bytes(self):
        resp = v3.V3RegistrationResponse()
        wire = resp.encode()
        self.assertEqual(len(wire), 88)
        self.assertEqual(wire[:3], b"\x00\x01\x03")
        self.assertEqual(wire[0x0F], 0x20)
        self.assertEqual(wire[0x30], 0x23)
        self.assertEqual(wire[0x31:0x31 + 35].decode(), resp.server_version)
        self.assertEqual(wire[0x54:], bytes.fromhex("00000000"))

    def test_response_rejects_bad_token(self):
        with self.assertRaises(ValueError):
            v3.V3RegistrationResponse(session_token=b"short")


if __name__ == "__main__":
    unittest.main()
