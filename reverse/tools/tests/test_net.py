"""Passive network analysis tests (stdlib unittest).

`extract_sni` decides whether a pcapng can name the host behind an IP. It has
to work on a real ClientHello, which is the only shape the TLS library emits
and the only shape a capture ever contains.
"""

from __future__ import annotations

import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import net  # noqa: E402


def server_name_extension(host: bytes) -> bytes:
    """server_name extension: type=0, one host_name entry (type 0)."""
    entry = b"\x00" + struct.pack("!H", len(host)) + host
    return b"\x00\x00" + struct.pack("!H", 2 + len(entry)) + struct.pack(
        "!H", len(entry)
    ) + entry


def client_hello(host: bytes | None) -> bytes:
    """Minimal TLS 1.0-record ClientHello, optionally carrying SNI."""
    extensions = server_name_extension(host) if host else b""
    body = (
        b"\x03\x03"
        + b"\x00" * 32  # random
        + b"\x00"  # session id length
        + b"\x00\x02\x00\x2f"  # one cipher suite
        + b"\x01\x00"  # one compression method
        + struct.pack("!H", len(extensions))
        + extensions
    )
    handshake = b"\x01" + struct.pack("!I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack("!H", len(handshake)) + handshake


class ExtractSniTest(unittest.TestCase):
    def test_names_the_host_of_a_real_client_hello(self) -> None:
        hello = client_hello(b"tokenservice.amazongames.com")
        self.assertEqual(net.extract_sni(hello), "tokenservice.amazongames.com")

    def test_shorter_host_is_not_truncated_to_a_suffix(self) -> None:
        # Guards the name length: a wrong offset yields a shorter, wrong name.
        self.assertEqual(net.extract_sni(client_hello(b"a.io")), "a.io")

    def test_client_hello_without_sni_returns_none(self) -> None:
        self.assertIsNone(net.extract_sni(client_hello(None)))

    def test_non_tls_payload_returns_none(self) -> None:
        self.assertIsNone(net.extract_sni(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n" + b"\x00" * 32))


if __name__ == "__main__":
    unittest.main()
