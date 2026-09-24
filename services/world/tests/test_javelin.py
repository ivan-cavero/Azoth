"""Javelin library tests (stdlib unittest).

The round-trip rule: a parser that cannot reproduce its input byte-for-byte
is wrong. The synthetic V3 body is built from the layout constants in
research/docs/REP-PROTOCOL.md (gap sizes follow from the fixed offsets).
"""

from __future__ import annotations

import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azoth_world.javelin.wire import encode_vlq32  # noqa: E402


def _client_vlq_decode(buf: bytes) -> int:
    """Decode the way NewWorld 1.400 does (1s-prefix, see wire.encode_vlq32).

    Kept independent of the encoder so the test pins the WIRE contract, not
    an encoder/decoder pair that could agree while both being wrong.
    """
    b0 = buf[0]
    if b0 < 0x80:
        return b0 & 0x7F
    if b0 < 0xC0:
        n, bits = 2, 6
    elif b0 < 0xE0:
        n, bits = 3, 5
    elif b0 < 0xF0:
        n, bits = 4, 4
    else:
        n, bits = 5, 3
    value = b0 & ((1 << bits) - 1)
    shift = bits
    for i in range(1, n):
        value |= buf[i] << shift
        shift += 8
    return value


class TestVlq32(unittest.TestCase):
    """The length prefix before every replayed typed-stream body.

    Regression 2026-09-24: the old encoder was LSB-first/7-bit. Both
    schemes agree below 64, so the small replay messages worked and the
    client silently truncated the 12706-byte one to 6370 -- a magic number
    that is exactly (0x63 << 6) | 0x22, the old `a2 63` read with the
    client's rule. Fixing the encoder unblocked the whole stream.
    """

    def test_roundtrip_against_client_decoder(self) -> None:
        for value in (
            0, 1, 12, 63, 64, 76, 88, 127, 128, 255, 1000, 4095, 4096,
            6370, 8803, 12706, 46423, 99819, 2640000, 50_000_000,
        ):
            with self.subTest(value=value):
                encoded = encode_vlq32(value)
                self.assertEqual(_client_vlq_decode(encoded), value)

    def test_known_encodings(self) -> None:
        # Pinned so a future "simplification" back to 7-bit LSB-first fails.
        self.assertEqual(encode_vlq32(12), b"\x0c")
        self.assertEqual(encode_vlq32(6370), b"\xa2\x63")
        self.assertEqual(encode_vlq32(12706), b"\xa2\xc6")

    def test_rejects_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            encode_vlq32(-1)
        with self.assertRaises(ValueError):
            encode_vlq32(1 << 35)

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
from azoth_world.javelin.replay_store import (  # noqa: E402
    ReplayMessage,
    apply_span_substitution,
    remap_fresh_levelinfo_key,
    remap_replay_identity,
    remap_selfident_guid,
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


def make_retry_v3_body(
    *,
    ticket: str = "29d426a8-a792-4fbc-bbb8-b4d666c01081",
    world: str = "00000000-0000-4000-8000-000000000001",
    character: str = "11111111-1111-1111-1111-111111111111",
    persona_uuid: str = "fc906c07-42a2-2dd1-f59f-9c56cf4f212c",
    persona_field: str | None = None,
    include_session: bool = True,
) -> bytes:
    records = ((0, "[RETAIL]"), (1, "Javelin"), (2, "1"), (3, "400"), (4, "6031"), (5, "6004151"))
    out = bytearray(b"\x00" * 32)
    for type_id, text in records:
        raw = text.encode("ascii")
        out += struct.pack(">I", type_id) + bytes((len(raw),)) + raw
    out.append(0)
    identity = [
        f"sig:{ticket}",
        "127.0.0.1:9000",
        world,
        character,
        persona_field or persona_uuid,
    ]
    if include_session:
        identity.append(ticket)
    identity.extend(("76561197960287930", "steam|14"))
    for text in identity:
        raw = text.encode("ascii")
        out += bytes((len(raw),)) + raw
    out += b"\xff\xfb\x00\x11"  # opaque auth tail; parser must stop safely
    return bytes(out)


class TestReplayIdentityRemap(unittest.TestCase):
    def setUp(self):
        self.message = ReplayMessage(
            seq=0x28,
            type_id=0x16A0,
            direction="R",
            body=bytes(153),
            has_redaction=True,
            redacted_spans=[(0x5C, 36)],
        )

    def test_disabled_is_identity(self):
        out = remap_replay_identity(
            self.message,
            selector="off",
            character_id="11111111-1111-1111-1111-111111111111",
        )
        self.assertIs(out, self.message)

    def test_character_remap_is_same_length_and_copies_source(self):
        out = remap_replay_identity(
            self.message,
            selector="character",
            character_id="11111111-1111-1111-1111-111111111111",
        )
        self.assertIsNot(out, self.message)
        self.assertEqual(len(out.body), len(self.message.body))
        self.assertEqual(
            out.body[0x5C:0x5C + 36],
            b"11111111-1111-1111-1111-111111111111",
        )
        self.assertEqual(self.message.body[0x5C:0x5C + 36], bytes(36))
        self.assertEqual(out.redacted_spans, self.message.redacted_spans)

    def test_session_selector_and_unknown_fail_closed(self):
        out = remap_replay_identity(
            self.message,
            selector="session",
            session_uuid="974b84a5-c736-42ab-a292-db6f21bdd4da",
        )
        self.assertEqual(
            out.body[0x5C:0x5C + 36],
            b"974b84a5-c736-42ab-a292-db6f21bdd4da",
        )
        self.assertIs(
            remap_replay_identity(
                self.message,
                selector="persona",
                character_id="11111111-1111-1111-1111-111111111111",
            ),
            self.message,
        )

    def test_nonzero_slot_is_never_overwritten(self):
        source = ReplayMessage(
            seq=0x28,
            type_id=0x16A0,
            direction="R",
            body=b"X" * 153,
            has_redaction=False,
        )
        self.assertIs(
            remap_replay_identity(
                source,
                selector="character",
                character_id="11111111-1111-1111-1111-111111111111",
            ),
            source,
        )


class TestSelfIdentGuidRemap(unittest.TestCase):
    def setUp(self):
        self.message = ReplayMessage(
            seq=0x06,
            type_id=0x065C,
            direction="R",
            body=bytes(0x06 + 0x10 + 8),
            has_redaction=True,
            redacted_spans=[(0x05, 16)],
        )

    def test_session_guid_is_same_length_and_copies_source(self):
        out = remap_selfident_guid(
            self.message,
            selector="session",
            session_uuid="974b84a5-c736-42ab-a292-db6f21bdd4da",
        )
        self.assertIsNot(out, self.message)
        self.assertEqual(len(out.body), len(self.message.body))
        self.assertEqual(
            out.body[0x05:0x15],
            bytes.fromhex("974b84a5c73642aba292db6f21bdd4da"),
        )
        self.assertEqual(self.message.body[0x05:0x15], bytes(16))

    def test_invalid_or_disabled_selector_fails_closed(self):
        self.assertIs(
            remap_selfident_guid(
                self.message,
                selector="off",
                session_uuid="974b84a5-c736-42ab-a292-db6f21bdd4da",
            ),
            self.message,
        )
        self.assertIs(
            remap_selfident_guid(
                self.message,
                selector="session",
                session_uuid="not-a-uuid",
            ),
            self.message,
        )

    def test_nonzero_slot_is_never_overwritten(self):
        source = ReplayMessage(
            seq=0x06,
            type_id=0x065C,
            direction="R",
            body=b"X" * (0x06 + 0x10 + 8),
            has_redaction=False,
        )
        self.assertIs(
            remap_selfident_guid(
                source,
                selector="character",
                character_id="11111111-1111-1111-1111-111111111111",
            ),
            source,
        )


class TestSpanSubstitution(unittest.TestCase):
    CHARACTER = "11111111-1111-1111-1111-111111111111"
    SESSION = "974b84a5-c736-42ab-a292-db6f21bdd4da"
    PERSONA = "amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c"

    def setUp(self):
        self.message = ReplayMessage(
            seq=0x2A,
            type_id=0x0008,
            direction="R",
            body=bytes(0x100),
            has_redaction=True,
            redacted_spans=[
                (0x04, 16),
                (0x20, 36),
                (0x50, 20),
                (0x70, 61),
                (0xC0, 8),
            ],
        )

    def test_character_fills_binary_text_name_and_persona(self):
        out = apply_span_substitution(
            self.message,
            selector="character",
            character_id=self.CHARACTER,
            persona_id=self.PERSONA,
            display_name="Tester",
        )
        self.assertIsNot(out, self.message)
        self.assertEqual(len(out.body), 0x100)
        self.assertEqual(
            out.body[0x04:0x14],
            bytes.fromhex("11111111111111111111111111111111"),
        )
        self.assertEqual(
            out.body[0x20:0x44],
            self.CHARACTER.encode("ascii"),
        )
        self.assertEqual(out.body[0x50:0x64], b"Tester" + b"0" * 14)
        self.assertEqual(
            out.body[0x70:0xAD],
            self.PERSONA.encode("ascii"),
        )
        self.assertEqual(out.body[0xC0:0xC8], bytes(8))  # CRC stays zero

    def test_session_selector_uses_session_uuid(self):
        out = apply_span_substitution(
            self.message,
            selector="session",
            session_uuid=self.SESSION,
            persona_id=self.PERSONA,
        )
        self.assertEqual(
            out.body[0x04:0x14],
            bytes.fromhex("974b84a5c73642aba292db6f21bdd4da"),
        )
        self.assertEqual(
            out.body[0x20:0x44],
            self.SESSION.encode("ascii"),
        )

    def test_seq_scope_limits_changes(self):
        out = apply_span_substitution(
            self.message,
            selector="character",
            character_id=self.CHARACTER,
            seqs={0x8C},
        )
        self.assertIs(out, self.message)
        out = apply_span_substitution(
            self.message,
            selector="character",
            character_id=self.CHARACTER,
            seqs={0x2A},
        )
        self.assertIsNot(out, self.message)

    def test_length_filter_limits_changes(self):
        out = apply_span_substitution(
            self.message,
            selector="character",
            character_id=self.CHARACTER,
            persona_id=self.PERSONA,
            lengths={16},
        )
        self.assertIsNot(out, self.message)
        self.assertNotEqual(out.body[0x04:0x14], bytes(16))
        self.assertEqual(out.body[0x20:0x44], bytes(36))
        self.assertEqual(out.body[0x50:0x64], bytes(20))

    def test_disabled_and_invalid_selector_fail_closed(self):
        self.assertIs(
            apply_span_substitution(self.message, selector="off"),
            self.message,
        )
        self.assertIs(
            apply_span_substitution(
                self.message,
                selector="not-a-real-selector",
                character_id=self.CHARACTER,
            ),
            self.message,
        )
        self.assertIs(
            apply_span_substitution(
                self.message,
                selector="character",
                character_id="not-a-uuid",
            ),
            self.message,
        )


class TestFreshLevelInfoRemap(unittest.TestCase):
    def setUp(self):
        body = bytearray(110)
        body[0x66:0x6E] = bytes.fromhex("000000c17f9be48f")
        self.message = ReplayMessage(
            seq=0x4D,
            type_id=0x0663,
            direction="R",
            body=bytes(body),
            has_redaction=False,
        )

    def test_session_key_is_replaced_only_on_duplicate_record(self):
        out = remap_fresh_levelinfo_key(
            self.message,
            selector="session",
            session_uuid="974b84a5-c736-42ab-a292-db6f21bdd4da",
        )
        self.assertIsNot(out, self.message)
        self.assertEqual(
            out.body[0x66:0x6E],
            bytes.fromhex("974b84a5c73642ab"),
        )
        self.assertEqual(self.message.body[0x66:0x6E], bytes.fromhex("000000c17f9be48f"))

    def test_wrong_sequence_and_invalid_selector_fail_closed(self):
        source = ReplayMessage(
            seq=0x10,
            type_id=0x0663,
            direction="R",
            body=self.message.body,
            has_redaction=False,
        )
        self.assertIs(
            remap_fresh_levelinfo_key(
                source,
                selector="session",
                session_uuid="974b84a5-c736-42ab-a292-db6f21bdd4da",
            ),
            source,
        )
        self.assertIs(
            remap_fresh_levelinfo_key(self.message, selector="off"),
            self.message,
        )


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

    def test_retry_identity_fields_and_roundtrip(self):
        body = make_retry_v3_body()
        msg = v3.parse_v3_request_retry(body)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.client_signature, "sig:29d426a8-a792-4fbc-bbb8-b4d666c01081")
        self.assertEqual(msg.client_endpoint, "127.0.0.1:9000")
        self.assertEqual(msg.world_id, "00000000-0000-4000-8000-000000000001")
        self.assertEqual(msg.character_id, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(msg.session_uuid, "29d426a8-a792-4fbc-bbb8-b4d666c01081")
        self.assertEqual(
            msg.persona_id,
            "amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c",
        )
        self.assertEqual(msg.platform_user_id, "76561197960287930")
        self.assertEqual(msg.platform_name_blob, "steam|14")
        self.assertEqual(msg.sdk_version, "600415")
        self.assertEqual(msg.sdk_version_tail, ord("1"))
        self.assertEqual(v3.serialize_v3_request(msg), body)

    def test_retry_1400_uses_ticket_uuid_as_session(self):
        persona = "amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c"
        body = make_retry_v3_body(persona_field=persona, include_session=False)
        msg = v3.parse_v3_request_retry(body)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.session_uuid, "29d426a8-a792-4fbc-bbb8-b4d666c01081")
        self.assertEqual(msg.character_id, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(msg.persona_id, persona)
        self.assertEqual(v3.serialize_v3_request(msg), body)

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
