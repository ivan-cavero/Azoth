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
import re
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
BODIES = REPO / "research" / "fixtures" / "wire" / "wire-bodies.json"
CRATE_MOD = (
    REPO / "server" / "crates" / "everfall-wire" / "src" / "generated" / "mod.rs"
)
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

    def test_generated_codec_round_trips_extracted_bodies(self) -> None:
        """Every seeded layout with a real body must round-trip byte-exactly.

        `scripts/export/export-wire-bodies.py` extracts one real BODY per target
        layout from the committed corpus or a local log and writes
        `wire-bodies.json`. Each body here is fed through the GENERATED codec:
        `encode(decode(body)) == body`. A record whose wire is not codegen-ready
        is reported and skipped -- never replaced by a weaker assertion.
        """
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run `python ef.py re ontology-gen`")
        self.assertTrue(BODIES.is_file(), f"missing extracted-body fixture: {BODIES}")
        fixture = json.loads(BODIES.read_text(encoding="utf-8"))
        records = fixture["records"]
        self.assertTrue(records, "wire-bodies.json has no records")

        ready_wires = set(wire.MESSAGES)
        checked = 0
        skipped: list[str] = []
        for record in records:
            wire_id = int(record["wire_id"])
            body = bytes.fromhex(record["body"])
            if wire_id not in ready_wires:
                skipped.append(f"wire {hex(wire_id)} is not codegen-ready")
                continue
            decoded = wire.decode(wire_id, body)
            self.assertEqual(
                wire.encode(wire_id, decoded),
                body,
                f"wire {hex(wire_id)} ({record['source']}): body did not round-trip",
            )
            checked += 1
        self.assertGreater(
            checked, 0, "no extracted body round-tripped: " + "; ".join(skipped)
        )

        # The newly seeded layouts with a real body must be codegen-ready.
        for wire_id in (0x3, 0x65C, 0x663, 0xF37):
            self.assertIn(wire_id, ready_wires, f"wire {hex(wire_id)} should be ready")

    def test_generated_codec_round_trips_entry_bodies(self) -> None:
        """The three world-entry bodies the server must SEND round-trip exactly.

        `0x3` (RegistrationResponseMsg) and `0x663` (LevelInfoChangedMsg) were
        refused until their cards were repaired; this pins that they are now
        codegen-ready and that the GENERATED codec reproduces their extracted
        bytes byte-for-byte. The body comes from `wire-bodies.json` (extracted by
        `scripts/export/export-wire-bodies.py` from the committed corpus), never a
        hand-pasted layout.
        """
        wire = load_generated_wire()
        self.assertIsNotNone(
            wire, f"{WIRE_PY} is missing; run `python ef.py re ontology-gen`"
        )
        fixture = json.loads(BODIES.read_text(encoding="utf-8"))
        by_wire: dict[int, list[dict]] = {}
        for record in fixture["records"]:
            by_wire.setdefault(int(record["wire_id"]), []).append(record)
        for wire_id in (0x3, 0x663):
            self.assertIn(
                wire_id, wire.MESSAGES, f"wire {hex(wire_id)} is not codegen-ready"
            )
            self.assertIn(
                wire_id, by_wire, f"no extracted body for wire {hex(wire_id)}"
            )
            for record in by_wire[wire_id]:
                body = bytes.fromhex(record["body"])
                decoded = wire.decode(wire_id, body)
                self.assertEqual(
                    wire.encode(wire_id, decoded),
                    body,
                    f"wire {hex(wire_id)} ({record['source']}): body did not round-trip",
                )

    def test_generator_emits_compiling_crate_and_stays_in_sync(self) -> None:
        """The Rust output is a crate copy, and it carries no bare byte field.

        The generator writes the exact same `wire.rs` text into the crate. This
        re-runs the generator into a temp crate path and checks three things the
        anti-emulator rule needs: the crate copy equals the reviewed `wire.rs`,
        the committed crate file has not drifted, and no generated struct
        declares a bare `Vec<u8>`/`&[u8]` field (an unnamed run is an `Opaque`).
        """
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            crate = Path(tmp) / "generated" / "mod.rs"
            report = generator.generate(SCHEMA, CONCEPTS, out, crate)
            self.assertIsNotNone(report["crate_artifact"])
            produced = crate.read_text(encoding="utf-8")
            self.assertEqual(
                produced,
                (out / "wire.rs").read_text(encoding="utf-8"),
                "the crate copy and the reviewed wire.rs differ",
            )
            self.assertTrue(CRATE_MOD.is_file(), f"missing crate module: {CRATE_MOD}")
            self.assertEqual(
                produced,
                CRATE_MOD.read_text(encoding="utf-8"),
                "the committed crate has drifted from the generator",
            )

            bare = re.compile(r"^\s*pub [A-Za-z_][A-Za-z0-9_]*:\s*(?:Vec<u8>|&\[u8\])")
            offenders = [line for line in produced.splitlines() if bare.match(line)]
            self.assertEqual(offenders, [], f"bare byte field(s): {offenders}")

            for needle in ("pub fn decode", "pub fn encode", "pub struct"):
                self.assertIn(needle, produced)

    def test_literal_count_vec_encodes_fixed_items(self) -> None:
        """`vec<f32be>` with a LITERAL `count` is a fixed run with no prefix.

        STEP 1: the vocabulary already allows `count` to be a JSON integer. The
        generator must carry it into the emitted codec, where it means exactly
        that many elements and NO length prefix (unlike `count: prefix_varint`).
        """
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            out = Path(tmp) / "out"
            concepts.mkdir()
            card = concept(
                uid="msg.level-bounds",
                wire={"id": "0x663", "direction": "S2C", "transport": "rep"},
                fields=[
                    {
                        "name": "bounds",
                        "type": "vec<f32be>",
                        "count": 4,
                        "evidence": "measured",
                    }
                ],
            )
            (concepts / "msg.level-bounds.json").write_text(
                json.dumps(card), encoding="utf-8"
            )
            report = generator.generate(SCHEMA, concepts, out)
            self.assertIn("msg.level-bounds", report["emitted"])

            spec = importlib.util.spec_from_file_location(
                "literal_count_wire_under_test", out / "wire.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Four BE floats with NO count prefix: exactly 16 bytes.
            body = bytes.fromhex("4500000041800000463fc00046202800")
            self.assertEqual(len(body), 16)
            decoded = module.decode(0x663, body)
            self.assertEqual(decoded["bounds"], [2048.0, 16.0, 12272.0, 10250.0])
            self.assertEqual(module.encode(0x663, decoded), body)

    def test_seeded_spend_layout_is_typed_but_has_no_body(self) -> None:
        """0x5de is fully typed and codegen-ready, but no real body exists.

        The committed corpus and the scanned local logs carry no 0x5de record, so
        the card stays a `typed but unverified` layout: present and emitted, but
        absent from wire-bodies.json. This pins the honest outcome so nobody
        fabricates a fixture for it.
        """
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        self.assertIn(0x5DE, wire.MESSAGES)
        fixture = json.loads(BODIES.read_text(encoding="utf-8"))
        for record in fixture["records"]:
            self.assertNotEqual(int(record["wire_id"]), 0x5DE)

    def test_gate_emits_codec_cards_separately(self) -> None:
        """A ready card with no wire id is a nested sub-codec, not a message."""
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            out = Path(tmp) / "out"
            concepts.mkdir()
            card = concept(
                uid="codec.example",
                kind="codec",
                fields=[
                    {"name": "blob", "type": "prefixed_bytes", "evidence": "partial", "max": 8}
                ],
            )
            (concepts / "codec.example.json").write_text(
                json.dumps(card), encoding="utf-8"
            )
            report = generator.generate(SCHEMA, concepts, out)
            self.assertEqual(report["emitted"], [])
            self.assertEqual([c["uid"] for c in report["codecs"]], ["codec.example"])
            rendered = (out / "wire.py").read_text(encoding="utf-8")
            self.assertIn("'codec.example'", rendered)
            self.assertIn("CODECS", rendered)
            messages_block = rendered.split("MESSAGES = {", 1)[1].split("CODECS = {", 1)[0]
            self.assertNotIn("codec.example", messages_block)

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
            and (card.get("wire") or {}).get("id") is not None
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
