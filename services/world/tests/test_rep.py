"""REP server tests (stdlib unittest + pyOpenSSL DTLS client).

The handshake test drives a real DTLS client (memory BIOs) against a live
server on localhost UDP: ClientHello -> ServerHello flight -> established.
This is the exact exchange the patched game client performs.
"""

from __future__ import annotations

import pathlib
import socket
import sys
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


class TestResponseDatagram(unittest.TestCase):
    def test_v3_response_is_parseable(self):
        wire = v3_response_datagram(7)
        env, body = parse_envelope(wire)
        self.assertEqual(env.sequence, 7)
        result = parse_datagram(body)
        self.assertIsNone(result.error)
        rec = result.messages[0]
        self.assertEqual(rec.flags, 0xE0)
        self.assertEqual(len(rec.payload), 88)
        self.assertEqual(rec.payload[:3], b"\x00\x01\x03")


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
        # 88-byte RegistrationResponseMsg back.
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
        self.assertIsNone(result.error)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(len(result.messages[0].payload), 88)
        udp.close()
        srv.sock.close()


if __name__ == "__main__":
    unittest.main()
