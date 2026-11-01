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
import sys
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
PRESENCE_FIXTURE = REPO / "research" / "fixtures" / "wire" / "state-fragment-3857.hex"
ENTITLEMENT_FIXTURE = REPO / "research" / "fixtures" / "wire" / "state-fragment-3133.hex"
TRANSMOG_FIXTURE = REPO / "research" / "fixtures" / "wire" / "state-fragment-5691.hex"
SOCIAL_FIXTURE = REPO / "research" / "fixtures" / "wire" / "state-fragment-4176.hex"
STATUS_EFFECTS_FIXTURE = REPO / "research" / "fixtures" / "wire" / "state-fragment-4236.hex"

# The generated module imports the measured prefix-varint primitive from the
# world service by a path relative to itself, so a copy written into a temp
# directory needs that source tree on the import path.
WORLD_SRC = REPO / "services" / "world" / "src"
if str(WORLD_SRC) not in sys.path:
    sys.path.insert(0, str(WORLD_SRC))
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


def hex_body(path: Path) -> bytes:
    """The bytes of one `#`-commented whitespace-wrapped hex fixture."""
    hexes: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0]
        hexes.append("".join(line.split()))
    return bytes.fromhex("".join(hexes))


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

    # --- the presence, nested, counted and optional constructs ---------------

    def test_a_second_presence_masked_component_needs_no_new_code(self) -> None:
        """Generality: a DIFFERENT two-level presence record, generated as-is.

        This card has nothing to do with the objectives family: group 2, members
        0 and 5, one scalar member and one counted container of a nested record.
        If the generator had special-cased the objectives card this body could
        not decode, so the test is the proof that the vocabulary -- not the
        generator -- carries the shape.
        """
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            out = Path(tmp) / "out"
            concepts.mkdir()
            item = concept(
                uid="codec.example-item",
                kind="codec",
                name="ExampleItem",
                fields=[{"name": "item_id", "type": "u64be", "evidence": "measured"}],
            )
            masked = concept(
                uid="codec.example-presence",
                kind="codec",
                name="ExamplePresence",
                presence={
                    "group": {"name": "group_mask", "bits": 8},
                    "member": {"name": "entry_mask", "bits": 7, "continuation": 128},
                },
                fields=[
                    {
                        "name": "leader",
                        "type": "u32be",
                        "evidence": "measured",
                        "presence": {"group": 2, "member": 0},
                    },
                    {
                        "name": "items",
                        "type": "counted(nested(codec.example-item))",
                        "evidence": "measured",
                        "presence": {"group": 2, "member": 5},
                    },
                ],
            )
            (concepts / "codec.example-item.json").write_text(
                json.dumps(item), encoding="utf-8"
            )
            (concepts / "codec.example-presence.json").write_text(
                json.dumps(masked), encoding="utf-8"
            )
            report = generator.generate(SCHEMA, concepts, out)
            self.assertEqual(report["refused"], [])
            self.assertEqual(
                [spec["uid"] for spec in report["codecs"]],
                ["codec.example-item", "codec.example-presence"],
            )

            spec = importlib.util.spec_from_file_location(
                "presence_wire_under_test", out / "wire.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # group 2 present (0x04), members 0 and 5 (0x21), then the bodies.
            body = bytes.fromhex("0421" "00000007" "02" "0000000000000001" "0000000000000002")
            decoded = module.decode_codec("codec.example-presence", body)
            self.assertEqual(decoded["group_mask"], 0x04)
            self.assertEqual(decoded["groups"][0]["entry_mask"], 0x21)
            self.assertEqual(decoded["groups"][0]["entries"]["leader"], 7)
            self.assertEqual(
                decoded["groups"][0]["entries"]["items"],
                [{"item_id": 1}, {"item_id": 2}],
            )
            self.assertEqual(module.encode_codec("codec.example-presence", decoded), body)

            # A set bit for a member the card does not declare is refused.
            with self.assertRaises(module.WireCodecError):
                module.decode_codec("codec.example-presence", bytes.fromhex("0401"))

    def test_measured_presence_body_round_trips_through_the_generated_codec(self) -> None:
        """The 1736-byte measured body through the GENERATED sub-codec table."""
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        hexes: list[str] = []
        for line in PRESENCE_FIXTURE.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0]
            hexes.append("".join(line.split()))
        body = bytes.fromhex("".join(hexes))
        self.assertEqual(len(body), 1736)
        self.assertEqual(body[:2], bytes([0x02, 0x18]))
        decoded = wire.decode_codec("codec.objectives-replicated-state", body)
        self.assertEqual(decoded["groups"][0]["entry_mask"], 0x18)
        active = decoded["groups"][0]["entries"]["activeObjectives"]
        tasks = decoded["groups"][0]["entries"]["taskStates"]
        self.assertEqual(active["delta"], 7)
        self.assertEqual(len(active["elements"]), 17)
        self.assertEqual(tasks["delta"], 7)
        self.assertEqual(len(tasks["elements"]), 43)
        self.assertEqual(wire.encode_codec("codec.objectives-replicated-state", decoded), body)

    def test_measured_entitlement_body_round_trips_through_the_generated_codec(self) -> None:
        """The 3892-byte body of state type 3133, through the GENERATED codec table."""
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        body = hex_body(ENTITLEMENT_FIXTURE)
        self.assertEqual(len(body), 3892)
        self.assertEqual(body[:2], bytes([0x01, 0x07]))
        decoded = wire.decode_codec("codec.entitlement-replicated-state", body)
        self.assertEqual(decoded["group_mask"], 0x01)
        self.assertEqual(decoded["groups"][0]["entry_mask"], 0x07)
        entitlements = decoded["groups"][0]["entries"]["entitlements"]
        balances = decoded["groups"][0]["entries"]["balances"]
        self.assertEqual(entitlements["delta"], 11)
        self.assertEqual(len(entitlements["elements"]), 423)
        self.assertEqual(balances["delta"], 11)
        self.assertEqual(len(balances["elements"]), 432)
        self.assertEqual(
            balances["elements"][0], {"left": 1424557555, "right": 1}
        )
        self.assertTrue(decoded["groups"][0]["entries"]["entitlementsReceived"])
        self.assertEqual(
            wire.encode_codec("codec.entitlement-replicated-state", decoded), body
        )

    def test_measured_transmog_body_round_trips_through_the_generated_codec(self) -> None:
        """The 834-byte body of state type 5691, through the GENERATED codec table."""
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        body = hex_body(TRANSMOG_FIXTURE)
        self.assertEqual(len(body), 834)
        self.assertEqual(body[:2], bytes([0x01, 0x13]))
        decoded = wire.decode_codec("codec.transmog-replicated-state", body)
        self.assertEqual(decoded["group_mask"], 0x01)
        self.assertEqual(decoded["groups"][0]["entry_mask"], 0x13)
        armor = decoded["groups"][0]["entries"]["capturedArmorAppearances"]
        weapon = decoded["groups"][0]["entries"]["capturedWeaponAppearances"]
        self.assertEqual(len(armor["elements"]), 39)
        self.assertEqual(armor["elements"][0]["id"], 0)
        self.assertEqual(armor["elements"][0]["delta"], 17)
        self.assertEqual(armor["elements"][0]["value"], 113979878627278848)
        self.assertEqual(armor["elements"][1]["id"], 1)
        self.assertEqual(armor["elements"][1]["delta"], 0)
        self.assertEqual(weapon["delta"], 17)
        self.assertEqual(len(weapon["elements"]), 49)
        self.assertEqual(weapon["elements"][0], 0x0040_0000_0000_0000)
        self.assertTrue(decoded["groups"][0]["entries"]["inventoryServicesReady"])
        self.assertEqual(
            wire.encode_codec("codec.transmog-replicated-state", decoded), body
        )

    def test_measured_social_body_round_trips_through_the_generated_codec(self) -> None:
        """The 55-byte body of state type 4176, through the GENERATED codec table."""
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        body = hex_body(SOCIAL_FIXTURE)
        self.assertEqual(len(body), 55)
        self.assertEqual(body[:2], bytes([0x02, 0x38]))
        decoded = wire.decode_codec("codec.social-replicated-state", body)
        self.assertEqual(decoded["group_mask"], 0x02)
        self.assertEqual(decoded["groups"][0]["entry_mask"], 0x38)
        entries = decoded["groups"][0]["entries"]
        self.assertEqual(entries["lastDailyResetTime"], 0x18AB_B402_9A5C_FB9C)
        friends = entries["friends"]
        self.assertEqual(friends["deltaCount"], 0)
        self.assertEqual(friends["delta"], 7)
        self.assertEqual(len(friends["elements"]), 1)
        self.assertEqual(friends["elements"][0], {"value": "\x00" * 36})
        invites = entries["friendInvites"]
        self.assertEqual(invites["delta"], 7)
        self.assertEqual(invites["elements"], [])
        self.assertEqual(
            wire.encode_codec("codec.social-replicated-state", decoded), body
        )

    def test_measured_status_effects_body_round_trips_through_the_generated_codec(
        self,
    ) -> None:
        """The 26-byte body of state type 4236, through the GENERATED codec table."""
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        body = hex_body(STATUS_EFFECTS_FIXTURE)
        self.assertEqual(len(body), 26)
        self.assertEqual(body[:2], bytes([0x02, 0x02]))
        decoded = wire.decode_codec(
            "codec.status-effects-component-replicated-state", body
        )
        self.assertEqual(decoded["group_mask"], 0x02)
        self.assertEqual(decoded["groups"][0]["entry_mask"], 0x02)
        effects = decoded["groups"][0]["entries"]["m_lightweightLocalEffectsMap"]
        self.assertEqual(effects["deltaCount"], 0)
        self.assertEqual(effects["delta"], 8)
        self.assertEqual(
            effects["elements"],
            [
                {"u16_a00": 0x0728, "u64_a08": 0xFFE5},
                {"u16_a00": 0x010F, "u64_a08": 0xFFE5},
            ],
        )
        self.assertEqual(
            wire.encode_codec(
                "codec.status-effects-component-replicated-state", decoded
            ),
            body,
        )

    def test_a_masked_element_bit_the_body_does_not_set_is_refused(self) -> None:
        """A clear mask bit declares an element the card cannot lay out."""
        wire = load_generated_wire()
        self.assertIsNotNone(wire, f"{WIRE_PY} is missing; run the generator")
        body = bytearray(hex_body(TRANSMOG_FIXTURE))
        # The untouched body must decode, so the refusal below is about the mask
        # and not about a codec that is missing altogether.
        wire.decode_codec("codec.transmog-replicated-state", bytes(body))
        # byte 3 is the first element mask byte of the armor appearance map.
        self.assertEqual(body[3], 0xFF)
        body[3] = 0xFE
        with self.assertRaises(wire.WireCodecError):
            wire.decode_codec("codec.transmog-replicated-state", bytes(body))

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


    # --- the meaning gap is carried into the artifacts ------------------------

    def test_layout_only_field_is_emitted_not_refused(self) -> None:
        """Marking a field layout-only is visibility, never a gate.

        The layout is known, so the codec is correct: a card whose every field is
        `layout-only` must still be emitted, never refused.
        """
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            out = Path(tmp) / "out"
            concepts.mkdir()
            card = concept(
                wire={"id": "0x123", "direction": "S2C", "transport": "rep"},
                fields=[
                    {
                        "name": "field_a",
                        "type": "u64be",
                        "evidence": "measured",
                        "meaning": "layout-only",
                        "note": "shared head; meaning unnamed",
                    }
                ]
            )
            (concepts / "msg.example.json").write_text(
                json.dumps(card), encoding="utf-8"
            )
            report = generator.generate(SCHEMA, concepts, out)
            self.assertEqual(report["refused"], [])
            self.assertIn("msg.example", report["emitted"])

    def test_artifacts_label_known_and_layout_only(self) -> None:
        """The generated markdown and Rust both carry the meaning split."""
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            out = Path(tmp) / "out"
            concepts.mkdir()
            card = concept(
                fields=[
                    {
                        "name": "actor_id",
                        "type": "u64be",
                        "evidence": "measured",
                        "meaning": "known",
                        "note": "the actor id",
                    },
                    {
                        "name": "field_a",
                        "type": "u64be",
                        "evidence": "measured",
                        "meaning": "layout-only",
                        "note": "shared head; meaning unnamed",
                    },
                ]
            )
            (concepts / "msg.example.json").write_text(
                json.dumps(card), encoding="utf-8"
            )
            generator.generate(SCHEMA, concepts, out)

            markup = (out / "meanings-table.md").read_text(encoding="utf-8")
            self.assertIn("| field | type | offset | evidence | meaning | note |", markup)
            self.assertIn("| known |", markup)
            self.assertIn("| layout-only |", markup)

            rust = (out / "wire.rs").read_text(encoding="utf-8")
            self.assertIn(
                "Body field `field_a` (`u64be`); meaning unnamed.",
                rust,
            )
            self.assertNotIn(
                "Body field `actor_id` (`u64be`); meaning unnamed.",
                rust,
            )
            # The struct's type and behaviour are untouched by the marking.
            self.assertIn("pub field_a: u64,", rust)
            self.assertIn("pub actor_id: u64,", rust)


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
