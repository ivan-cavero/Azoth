"""Falsification tests for the generated wire codec.

WHY THIS EXISTS
===============
`reverse/tools/atlas/ontology-gen.py` emits `research/generated/wire.py` from the
Atlas concept cards. A codec that only "looks right" is worthless: these tests
make the generated code reproduce REAL capture bytes, make the gate refuse the
cards that are not codegen-ready, and require two runs to be byte-identical.

THE IMPORTANT TEST decodes real fixture bytes with the GENERATED codec, not the
hand-written prototype: for every codegen-ready card that has a matching record in
`research/fixtures/wire/wire-fixtures.json` it extracts that record's body and
requires `encode(decode(body)) == body` byte-exactly. A card with no fixture
record is reported and skipped with the reason -- never replaced by a weaker
assertion.

A fixture record is treated as matching when its payload carries the canonical
typed envelope (`00 01` then the prefix-varint message type) on a DATA channel
(0/1/2). Channel 3 is Carrier system framing, where `00 01` is not the typed
envelope; excluding it avoids the coincidental `00 01 6a 06` system record being
read as an UpdateMsg.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]
GENERATOR = TOOLS / "atlas" / "ontology-gen.py"
GENERATED = REPO / "research" / "generated"
WIRE_PY = GENERATED / "wire.py"
SCHEMA = REPO / "research" / "atlas" / "ontology" / "schema.json"
CONCEPTS = REPO / "research" / "atlas" / "ontology" / "concepts"
FIXTURE = REPO / "research" / "fixtures" / "wire" / "wire-fixtures.json"
ARTIFACTS = ("wire.py", "wire.rs", "meanings-table.md")
TYPE_MARKER = b"\x00\x01"
DATA_CHANNELS = (0, 1, 2)


def load_generator():
    spec = importlib.util.spec_from_file_location("ontology_gen_under_test", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_generated_wire():
    if not WIRE_PY.is_file():
        return None
    spec = importlib.util.spec_from_file_location("generated_wire_under_test", WIRE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def concept(**overrides):
    base = {
        "uid": "msg.example",
        "kind": "message",
        "name": "ExampleMsg",
        "summary": "a fabricated card for the generator's own gate test",
        "confidence": "layout",
        "status": "candidate",
        "evidence": [{"type": "atlas", "ref": "test"}],
        "fields": [{"name": "count", "type": "u32be", "evidence": "partial"}],
    }
    base.update(overrides)
    return base


class OntologyGenTest(unittest.TestCase):
    # --- artifacts exist ------------------------------------------------------

    def test_generator_artifacts_exist(self) -> None:
        self.assertTrue(GENERATOR.is_file(), f"missing generator: {GENERATOR}")
        for name in ARTIFACTS:
            path = GENERATED / name
            self.assertTrue(path.is_file(), f"missing generated artifact: {path}")
            self.assertGreater(path.stat().st_size, 0, f"empty generated artifact: {path}")

    # --- THE IMPORTANT TEST: real bytes through the generated codec -----------

    def test_generated_codec_round_trips_fixture_records(self) -> None:
        generator = load_generator()
        wire = load_generated_wire()
        self.assertIsNotNone(
            wire, f"{WIRE_PY} is missing; run `python ef.py re ontology-gen`"
        )
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        ready = [
            card
            for card in _cards(CONCEPTS)
            if generator.classify(card)[0] == "ready"
        ]
        self.assertTrue(ready, "no codegen-ready card to falsify against")

        checked = 0
        skipped: list[str] = []
        for card in ready:
            wire_id = int(str(card["wire"]["id"]), 0)
            bodies = [
                body
                for _channel, wid, body in _typed_records(fixture, wire)
                if wid == wire_id
            ]
            if not bodies:
                skipped.append(
                    f"{card['uid']} (wire {wire_id}): no fixture record carries the "
                    f"typed envelope 00 01 {hex(wire_id)} on a data channel"
                )
                continue
            for body in bodies:
                decoded = wire.decode(wire_id, body)
                self.assertEqual(
                    wire.encode(wire_id, decoded),
                    body,
                    f"{card['uid']}: encode(decode(body)) != body",
                )
                checked += 1
        if checked == 0:
            self.skipTest(
                "no codegen-ready card has a matching fixture record: "
                + "; ".join(skipped)
            )

    def test_generated_codec_round_trips_real_bundle_lengths(self) -> None:
        """The generated codec on REAL capture bytes.

        No codegen-ready card has a matching typed fixture record (see the test
        above), but the codec the one ready card compiles to -- `prefixed_bytes`
        -- is the same shape as a state bundle's length-prefixed payload. This
        decodes and re-encodes that real byte region for every committed bundle,
        so the generated codec is falsified against the capture rather than only
        against a synthetic body.
        """
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundles = fixture["state_bundles"]
        self.assertTrue(bundles, "no state bundles to test")
        checked = 0
        for entry in bundles:
            body = bytes.fromhex(entry["body"])
            self.assertEqual(body[:3], b"\x00\x01\x08", "not a type-0x08 bundle body")
            _seq, after = wire.decode_field("prefix_varint", body, 4)
            region = body[after + 6:]  # skip the six invariant prologue bytes
            value, offset = wire.decode_field("prefixed_bytes", region)
            self.assertEqual(offset, len(region), "length prefix does not reach the end")
            self.assertEqual(
                wire.encode_field("prefixed_bytes", value),
                region,
                f"prefixed_bytes not byte-exact for {entry.get('source', 'bundle')}",
            )
            checked += 1
        self.assertGreater(checked, 0)

    # --- the gate: a fabricated not-ready card is refused, not emitted --------

    def test_gate_refuses_not_ready_card(self) -> None:
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            out = Path(tmp) / "out"
            concepts.mkdir()
            opaque = concept(
                uid="msg.opaque",
                fields=[{"name": "blob", "type": "opaque(blob)", "evidence": "measured"}],
            )
            unknown = concept(
                uid="msg.unknown-evidence",
                fields=[{"name": "first", "type": "u64be", "evidence": "unknown"}],
            )
            (concepts / "msg.opaque.json").write_text(json.dumps(opaque), encoding="utf-8")
            (concepts / "msg.unknown-evidence.json").write_text(
                json.dumps(unknown), encoding="utf-8"
            )
            report = generator.generate(SCHEMA, concepts, out)

            refused = dict(report["refused"])
            self.assertIn("msg.opaque", refused)
            self.assertIn("opaque", refused["msg.opaque"])
            self.assertIn("msg.unknown-evidence", refused)
            self.assertIn("unknown", refused["msg.unknown-evidence"])
            self.assertEqual(report["emitted"], [])

            wire_py = (out / "wire.py").read_text(encoding="utf-8")
            self.assertNotIn("msg.opaque", wire_py)
            self.assertNotIn("msg.unknown-evidence", wire_py)

            markup = (out / "meanings-table.md").read_text(encoding="utf-8")
            self.assertIn("msg.opaque", markup)
            self.assertIn("msg.unknown-evidence", markup)

    def test_gate_reports_fieldless_card(self) -> None:
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            out = Path(tmp) / "out"
            concepts.mkdir()
            fieldless = concept(uid="msg.fieldless", fields=[])
            (concepts / "msg.fieldless.json").write_text(
                json.dumps(fieldless), encoding="utf-8"
            )
            report = generator.generate(SCHEMA, concepts, out)
            self.assertIn("msg.fieldless", report["fieldless"])
            self.assertNotIn("msg.fieldless", report["emitted"])
            self.assertNotIn("msg.fieldless", [uid for uid, _ in report["refused"]])

    # --- determinism ----------------------------------------------------------

    def test_output_is_deterministic(self) -> None:
        generator = load_generator()
        digests = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                generator.generate(SCHEMA, CONCEPTS, out)
                digests.append(
                    [
                        hashlib.sha256((out / name).read_bytes()).hexdigest()
                        for name in ARTIFACTS
                    ]
                )
        self.assertEqual(digests[0], digests[1], "two runs differ byte-for-byte")

    # --- triangulation: the codec engine itself -------------------------------

    def test_prefixed_bytes_round_trip_and_truncation(self) -> None:
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        body = bytes([5]) + b"hello"
        values = wire.decode(106, body)
        self.assertEqual(values["blob"], b"hello")
        self.assertEqual(wire.encode(106, values), body)
        with self.assertRaises(wire.WireCodecError):
            wire.decode(106, bytes([5]) + b"hell")  # length says 5, only 4 remain
        with self.assertRaises(wire.WireCodecError):
            wire.decode(106, body + b"x")  # a trailing byte is not consumed


def _cards(concepts_dir: Path):
    for path in sorted(Path(concepts_dir).glob("*.json")):
        yield json.loads(path.read_text(encoding="utf-8"))


def _typed_records(fixture: dict, wire):
    """(channel, wire_id, body) for each fixture record carrying 00 01 <type>."""
    for entry in fixture.get("datagrams", []):
        for record in entry.get("records", []):
            payload = bytes.fromhex(record["payload"])
            if record.get("channel") not in DATA_CHANNELS:
                continue
            if len(payload) < 3 or payload[:2] != TYPE_MARKER:
                continue
            try:
                wire_id, offset = wire.decode_field("prefix_varint", payload, 2)
            except wire.WireCodecError:
                continue
            yield record["channel"], wire_id, payload[offset:]


if __name__ == "__main__":
    unittest.main()
