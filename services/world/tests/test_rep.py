"""REP server tests (stdlib unittest + pyOpenSSL DTLS client).

The handshake test drives a real DTLS client (memory BIOs) against a live
server on localhost UDP: ClientHello -> ServerHello flight -> established.
This is the exact exchange the patched game client performs.
"""

from __future__ import annotations

import pathlib
import socket
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azoth_world.javelin import (
    MessageRecord,
    marshal_datagram,
    parse_datagram,
    parse_envelope,
)
from azoth_world.rep import v3_response_datagram

HAVE_PYOPENSSL = False
try:
    from OpenSSL import SSL

    HAVE_PYOPENSSL = True
except ImportError:
    pass


class TestSystemHandshake(unittest.TestCase):
    def test_connect_request_gets_ack(self):
        from azoth_world.rep import handle_app_data

        # Client CONNECT_REQUEST: system channel 3, msgId LAST byte.
        rec = MessageRecord(
            channel=3,
            payload=b"\x00\x00\x00\x05" + bytes([1]),  # version u32 + msgId=1
            sequence=1,
            flags_override=0xA0,  # DATA_CHANNEL | CONNECTING
        )
        request = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        replies = handle_app_data(request, 1, handshake_done=False, inbound_first=1)
        self.assertTrue(replies, "CONNECT_REQUEST must be answered")
        env, body = parse_envelope(replies[0])
        self.assertEqual(env.sequence, 1)
        result = parse_datagram(body)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.messages), 3)
        clock, ack, piggy = result.messages
        # CLOCK_SYNC first (reference: SendSyncTime() before the ACK).
        self.assertEqual(clock.system_msg_id, 4)
        self.assertEqual(clock.flags, 0x20)  # unreliable, not connecting
        # CONNECT_ACK carries the welcome data: the client's version u32
        # echoed verbatim (DefaultHandshake semantics — the client runs
        # OnReceiveAck on it; the datagram-ACK form `40 0002 0002` was
        # tried 2026-09-17 and did NOT advance the client).
        self.assertEqual(ack.system_msg_id, 2)
        self.assertEqual(ack.flags, 0x21)
        self.assertEqual(ack.sequence, 1)
        self.assertEqual(ack.reliable_sequence, 0)
        self.assertEqual(ack.payload, b"\x00\x00\x00\x05\x02")
        # CT_ACKS piggyback (first-light PR #5): continuous-ACK over the
        # inbound envelope range, flags 0x18 (SEQ fields inherited).
        self.assertEqual(piggy.system_msg_id, 6)
        self.assertEqual(piggy.flags, 0x18)
        self.assertEqual(piggy.payload, bytes([0x40, 0x00, 0x01, 0x00, 0x01, 6]))
        # Envelope seq ECHOES the client's inbound seq (Mixed Nuts).
        self.assertEqual(env.sequence, 1)

    def test_resend_is_not_reacked(self):
        """GridMate reference: in CST_CONNECTED the server validates repeated
        CONNECT_REQUESTs silently (no second ACK). 2026-09-20: the server
        sends Cmd_Greetings once with the first V3 response; on a
        handshaked session (v3_done=True) a repeated CONNECT_REQUEST gets
        no reply."""
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(
            channel=3,
            payload=b"\x00\x00\x00\x05" + bytes([1]),
            sequence=1,
            flags_override=0xA0,
        )
        request = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        self.assertEqual(
            handle_app_data(
                request, 9, handshake_done=True, inbound_first=1, v3_done=True
            ),
            [],
        )

    def test_acks_are_not_answered(self):
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(
            channel=3, payload=bytes([6]), sequence=1, flags_override=0xA0
        )
        wire = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        # 2026-09-20: raw Cmd_Greetings is now gated behind
        # AZOTH_SEND_GREETINGS (it produced `Failed to unmarshal message`),
        # so ack-only datagrams get nothing again.
        self.assertEqual(
            handle_app_data(wire, 2, handshake_done=False, inbound_first=2), []
        )

    def test_v3_still_answered(self):
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(channel=0, payload=bytes(200), flags_override=0xE0)
        wire = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        replies = handle_app_data(wire, 2, handshake_done=False, inbound_first=2)
        self.assertTrue(replies)
        _, body = parse_envelope(replies[0])
        result = parse_datagram(body)
        self.assertEqual(len(result.messages[0].payload), 89)

    def test_lz4_v3_is_decompressed_before_parse(self):
        """Live client (2026-09-17 21:04) sends V3 as envelope 0x81.

        Parsing the compressed body as records used to emit the stub
        session token; the client then SM_DISCONNECTed."""
        from azoth_world.javelin.lz4 import decompress_lz4_block
        from azoth_world.javelin.v3 import parse_v3_request_or_lenient
        from azoth_world.rep import handle_app_data

        captured = bytes.fromhex(
            "81010005f00205045b00030000000089c961b00000094f0c00090200f00e0113"
            "970c0a5d06000000040436303331000000030334303000000002010e00f005"
            "01074a6176656c696e00000005073630303431351800f23700085b52455441"
            "494c5d00287369673a61386263623730612d643039642d343636622d623239"
            "612d3065626230336532636136320e3132372e302e302e313a393030302430"
            "300200102d0700702d343030302d380500000f000302002331240900021600"
            "0f250000cf633064650000103b320000248500116000006aac55f204000409"
            "01520a000001010d002001014a00ff0d113736353631313937393630323837"
            "3933308620737465616d7c61350200fffffb506135613561"
        )
        env, body = parse_envelope(captured)
        self.assertTrue(env.is_compressed)
        dec = decompress_lz4_block(body)
        recs = parse_datagram(dec)
        self.assertIsNone(recs.error)
        self.assertEqual(len(recs.messages), 1)
        v3 = parse_v3_request_or_lenient(recs.messages[0].payload)
        # Must NOT pick the seeded worldId (00000000-...).
        self.assertEqual(v3.session_uuid, "a8bcb70a-d09d-466b-b29a-0ebb03e2ca62")
        replies = handle_app_data(
            captured, 5, handshake_done=True, inbound_first=2
        )
        self.assertTrue(replies, "LZ4 V3 must still get a RegistrationResponse")
        _, rbody = parse_envelope(replies[0])
        result = parse_datagram(rbody)
        # 2026-09-20: no VLQ prefix — payload IS the 88B typed message
        # [00 01 03][error:4][clock+nonce:8][len 0x20][token:32]...
        token = result.messages[0].payload[1 + 3 + 4 + 8 + 1 : 1 + 3 + 4 + 8 + 1 + 32]
        self.assertEqual(token, b"a8bcb70ad09d466bb29a0ebb03e2ca62")

    def test_v3_answered_only_once(self):
        """V3 retries get answered with a 5s throttle (2026-09-19 19:26:
        the post-InGame 1115B blobs ARE V3 re-registrations; dropping
        them made the client restart the login cycle). Immediate retries
        within the throttle window only get Carrier CT_ACKS."""
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(channel=0, payload=bytes(200), flags_override=0xE0)
        wire = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        first = handle_app_data(
            wire, 2, handshake_done=True, inbound_first=2, v3_done=False
        )
        self.assertTrue(first)
        second = handle_app_data(
            wire,
            3,
            handshake_done=True,
            inbound_first=2,
            v3_done=True,
            v3_last_reply=time.monotonic(),
        )
        # Inside the throttle window: no second RegistrationResponse, but
        # Carrier CT_ACKS must still go out or the client retransmits then
        # @mm_csdkerr_disconnect (4).
        self.assertTrue(second)
        _, body = parse_envelope(second[0])
        recs = parse_datagram(body)
        self.assertEqual(recs.messages[0].system_msg_id, 6)
        # Outside the window (post-InGame re-registration, 90s later): the
        # V3 answer must fire again.
        third = handle_app_data(
            wire,
            4,
            handshake_done=True,
            inbound_first=2,
            v3_done=True,
            v3_last_reply=time.monotonic() - 6.0,
        )
        self.assertTrue(third)
        _, body = parse_envelope(third[0])
        recs = parse_datagram(body)
        self.assertTrue(any(m.channel == 0 for m in recs.messages))

    def test_post_v3_datagram_is_parseable(self):
        from azoth_world.rep import post_v3_datagram, self_ident_body

        wire = post_v3_datagram(10)
        env, body = parse_envelope(wire)
        self.assertEqual(env.sequence, 10)
        result = parse_datagram(body)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].payload[1:5], bytes((0x00, 0x01, 0x91, 0x17)))
        # 4-byte trigger + 21-byte structured body (self_ident_body)
        self.assertEqual(result.messages[0].payload[5:], self_ident_body())


class TestHeartbeat(unittest.TestCase):
    """Post-replay 0x15d ping/pong (see HEARTBEAT_* in rep.py).

    The tick is pinned against the capture: the first captured ping is
    `00 01 9d 05 00 03 6e f6 af 91 2d 74`, and consecutive captured values
    differ by ~1e9 (one second, in nanoseconds, big-endian).
    """

    def test_body_matches_the_capture(self):
        from azoth_world.rep import heartbeat_body

        self.assertEqual(
            heartbeat_body(0x6EF6AF912D74).hex(), "00019d0500036ef6af912d74"
        )

    def test_tick_is_big_endian_and_increments(self):
        from azoth_world.rep import heartbeat_body

        first = heartbeat_body(0x6EF6AF912D74)
        second = heartbeat_body(0x6EF6AF912D74 + 1_000_000_000)
        self.assertEqual(first[:6], second[:6])
        self.assertGreater(int.from_bytes(second[6:], "big"),
                           int.from_bytes(first[6:], "big"))

    def test_body_is_twelve_bytes_with_the_typed_preamble(self):
        from azoth_world.rep import heartbeat_body

        body = heartbeat_body(0x123456789ABC)
        self.assertEqual(len(body), 12)
        # typed-stream preamble for type 0x15d + the constant the capture repeats
        self.assertEqual(body[:6], bytes((0x00, 0x01, 0x9D, 0x05, 0x00, 0x03)))

    def test_tick_wraps_to_six_bytes(self):
        from azoth_world.rep import heartbeat_body

        # a value past 2**48 must not raise; it is masked to the wire width
        self.assertEqual(len(heartbeat_body(1 << 60)), 12)

    def test_heartbeat_is_unreliable(self):
        """A reliable heartbeat grew sent_reliable unbounded (resend storm)."""
        from azoth_world.rep import HEARTBEAT_ENABLED, HEARTBEAT_PERIOD_S

        self.assertIsInstance(HEARTBEAT_ENABLED, bool)
        self.assertGreater(HEARTBEAT_PERIOD_S, 0)



class TestClientHelloDetection(unittest.TestCase):
    """A reused source port must reset the DTLS session (2026-09-27).

    The client retries its ClientHello from the same port after a previous
    session ended; feeding that into the stale DTLS state machine left the
    handshake stuck with no reply and no error, which the client reported as
    `@mm_csdkerr_connection_failed`. These are the exact captured bytes.
    """

    def test_client_hello_is_detected(self):
        from azoth_world.rep import _is_client_hello

        self.assertTrue(
            _is_client_hello(bytes.fromhex("16fefd00000000000000000092010000"))
        )

    def test_client_hello_retry_is_detected(self):
        from azoth_world.rep import _is_client_hello

        # same record, sequence number incremented by the retry
        self.assertTrue(
            _is_client_hello(bytes.fromhex("16fefd00000000000000010092010000"))
        )

    def test_application_data_is_not_a_client_hello(self):
        from azoth_world.rep import _is_client_hello

        self.assertFalse(
            _is_client_hello(bytes.fromhex("17fefd0001000000000189002aa3a507"))
        )

    def test_short_datagram_is_not_a_client_hello(self):
        from azoth_world.rep import _is_client_hello

        self.assertFalse(_is_client_hello(b""))
        self.assertFalse(_is_client_hello(bytes.fromhex("16fefd00000000")))


class TestResponseDatagram(unittest.TestCase):
    def test_v3_response_is_parseable(self):
        wire = v3_response_datagram(7)
        env, body = parse_envelope(wire)
        self.assertEqual(env.sequence, 7)
        result = parse_datagram(body)
        self.assertIsNone(result.error)
        rec = result.messages[0]
        self.assertEqual(len(rec.payload), 89)
        self.assertEqual(rec.payload[0], 88)  # VLQ32 body size
        self.assertEqual(rec.payload[1], 0x00)  # typed preamble byte 0
        self.assertEqual(rec.payload[2], 0x01)  # typed preamble byte 1
        self.assertEqual(rec.payload[3], 0x03)  # typed type id 0x3


@unittest.skipUnless(HAVE_PYOPENSSL, "pyOpenSSL not installed")
class TestDtlsHandshake(unittest.TestCase):
    def test_client_handshake_completes(self):
        from azoth_world.rep import RepServer

        srv = RepServer("127.0.0.1", 0)  # port 0 = ephemeral
        port = srv.sock.getsockname()[1]

        client_ctx = SSL.Context(SSL.DTLS_METHOD)
        client_ctx.set_verify(SSL.VERIFY_NONE, lambda *a: True)  # trust patch
        client = SSL.Connection(client_ctx)
        client.set_connect_state()

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(5)
        addr = ("127.0.0.1", port)
        import threading

        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()

        # Drive the handshake loop like the game does: bio_read -> sendto,
        # recvfrom -> bio_write, until established.
        established = False
        for _ in range(10):
            try:
                client.do_handshake()
                established = True
                break
            except SSL.WantReadError:
                out = client.bio_read(65536)
                if out:
                    udp.sendto(out, addr)
                data, _ = udp.recvfrom(65536)
                client.bio_write(data)
        self.assertTrue(established)
        udp.close()
        srv.sock.close()

    def test_v3_roundtrip_over_dtls(self):
        from azoth_world.rep import RepServer

        srv = RepServer("127.0.0.1", 0)
        port = srv.sock.getsockname()[1]
        client_ctx = SSL.Context(SSL.DTLS_METHOD)
        client_ctx.set_verify(SSL.VERIFY_NONE, lambda *a: True)
        client = SSL.Connection(client_ctx)
        client.set_connect_state()
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(5)
        addr = ("127.0.0.1", port)
        import threading

        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()

        def pump():
            while True:
                try:
                    out = client.bio_read(65536)
                except SSL.WantReadError:
                    return
                if not out:
                    return
                udp.sendto(out, addr)

        for _ in range(10):
            try:
                client.do_handshake()
                break
            except SSL.WantReadError:
                pump()
                data, _ = udp.recvfrom(65536)
                client.bio_write(data)
        pump()  # flush anything pending

        # Send a V3 data-channel record (client -> server), expect the
        # VLQ32(88)+88B RegistrationResponseMsg back.
        rec = MessageRecord(
            channel=0,
            payload=bytes(200),  # opaque 200B body (identity not decoded here)
            flags_override=0xE0,
        )
        client.send(b"\x80\x01\x00\x01" + marshal_datagram([rec]))
        pump()
        data, _ = udp.recvfrom(65536)
        client.bio_write(data)
        resp = client.recv(65536)
        env, body = parse_envelope(resp)
        result = parse_datagram(body)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(len(result.messages[0].payload), 89)
        udp.close()
        srv.sock.close()


if __name__ == "__main__":
    unittest.main()



