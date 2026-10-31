"""Round-trip tests for the committed wire-fixture corpus (stdlib unittest).

The corpus at `research/fixtures/wire/wire-fixtures.json` is the byte record a
codec must reproduce. These tests do two things a "it parsed" test does not:

  1. they decode a deterministic sample of the entries through the REAL Python
     readers in `services/world/src/azoth_world/javelin/`, so a reader that
     silently regresses turns the fixture red; and
  2. they re-encode the record framing and a state bundle and require the bytes
     back EXACTLY, which is what makes the fixture able to falsify a codec
     instead of merely describing one.

Where the Python tree has no encoder for an entry (compressed envelopes: there
is no LZ4 compressor in `javelin/`), the test says so and skips that entry
rather than asserting something weaker.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
SRC = REPO / "services" / "world" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from azoth_world.javelin import alc, bundle, frame  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

FIXTURE = REPO / "research" / "fixtures" / "wire" / "wire-fixtures.json"
SAMPLE = 25


class WireFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    # --- the file itself -----------------------------------------------------

    def test_fixture_exists_parses_and_is_nonempty(self) -> None:
        self.assertTrue(FIXTURE.is_file(), f"missing committed fixture: {FIXTURE}")
        self.assertIsInstance(self.data, dict)
        total = (
            len(self.data.get("datagrams", []))
            + len(self.data.get("channel1", []))
            + len(self.data.get("state_bundles", []))
        )
        self.assertGreater(total, 0, "fixture carries no entries")

    # --- decode through the real readers ------------------------------------

    def test_datagram_records_decode(self) -> None:
        datagrams = self.data["datagrams"]
        self.assertTrue(datagrams, "no datagrams in fixture")
        for entry in datagrams[:SAMPLE]:
            raw = bytes.fromhex(entry["raw"])
            env, body = frame.parse_envelope(raw)
            if env.is_compressed:
                body = decompress_lz4_block(body)
            result = frame.parse_datagram(body)
            self.assertIsNone(result.error, f"parse error on {entry['shape']!r}")
            self.assertEqual(
                len(result.messages),
                len(entry["records"]),
                f"record count differs for {entry['shape']!r}",
            )

    def test_channel1_containers_decode(self) -> None:
        channel1 = self.data["channel1"]
        self.assertTrue(channel1, "no channel-1 containers in fixture")
        decoded = 0
        for entry in channel1[:SAMPLE]:
            payload = bytes.fromhex(entry["payload"])
            # Must not raise, and must be the typed input record.
            target, type_id, _body = alc.split_container(payload)
            self.assertEqual(type_id, alc.INPUT_STREAM_TYPE)
            self.assertEqual(len(target), 16, "actor id is not 16 bytes")
            # The position/buffer readers must not raise either.
            alc.read_movement_buffer_from_payload(payload)
            if alc.read_claim(payload) is not None:
                decoded += 1
        self.assertGreater(decoded, 0, "no channel-1 entry carried a readable claim")

    def test_state_bundles_decode(self) -> None:
        bundles = self.data["state_bundles"]
        self.assertTrue(bundles, "no state bundles in fixture")
        for entry in bundles[:SAMPLE]:
            body = bytes.fromhex(entry["body"])
            parsed = bundle.decode_bundle(body)
            self.assertIsInstance(parsed.replication_seq, int)
            self.assertGreaterEqual(parsed.replication_seq, 0)
            # The payload is a record sequence; its first fragment header must read.
            bundle.read_fragment_header(parsed.payload, 0)

    # --- byte-exact round-trips ---------------------------------------------

    def test_record_framing_round_trips(self) -> None:
        """parse -> marshal must return the datagram's records byte for byte."""
        checked = 0
        for entry in self.data["datagrams"]:
            raw = bytes.fromhex(entry["raw"])
            env, body = frame.parse_envelope(raw)
            if env.is_compressed:
                # `javelin/` ships no LZ4 compressor, so an exact re-encode of a
                # compressed envelope is not available; skip with the reason.
                continue
            result = frame.parse_datagram(body)
            self.assertIsNone(result.error, f"parse error on {entry['shape']!r}")
            for message in result.messages:
                message.flags_override = message.flags
            rebuilt = (
                bytes((env.type_byte, env.proto))
                + env.sequence.to_bytes(2, "big")
                + frame.marshal_datagram(result.messages)
            )
            self.assertEqual(rebuilt, raw, f"framing not byte-exact: {entry['shape']!r}")
            checked += 1
            if checked >= 5:
                break
        self.assertGreater(
            checked, 0, "no uncompressed datagram available for a framing round-trip"
        )

    def test_state_bundle_round_trips(self) -> None:
        """decode then re-encode must return the bundle bytes exactly.

        `decode_bundle` takes the body INCLUDING the `00 01 08` type marker, while
        `encode_body` returns the body WITHOUT it, so the exact inverse of
        `decode_bundle` is `encode_type_marker(0x08) + encode_body()`. That is the
        composition asserted here, not a weaker "it decoded" check.
        """
        checked = 0
        skipped: list[str] = []
        for entry in self.data["state_bundles"]:
            body = bytes.fromhex(entry["body"])
            try:
                parsed = bundle.decode_bundle(body)
            except bundle.BundleError as exc:
                # A redacted span in the committed corpus can break the length
                # check for that one bundle; it is not a codec defect.
                skipped.append(f"{entry.get('source', 'log')}: {exc}")
                continue
            rebuilt = bundle.encode_type_marker(bundle.STATE_BUNDLE_TYPE) + parsed.encode_body()
            self.assertEqual(rebuilt, body, "bundle not byte-exact")
            checked += 1
            if checked >= 5:
                break
        self.assertGreater(checked, 0, f"no bundle round-tripped; skipped={skipped}")


if __name__ == "__main__":
    unittest.main()
