"""The closed-field validator's four promised outcomes, on temp copies.

WHY THIS EXISTS. `reverse/tools/atlas/ontology-validate.py` is the only thing
that enforces the closed `fields` item schema in
`research/atlas/ontology/schema.json`. This test pins the four outcomes the
validator promises: a conforming card is ready, an invented codec fails, an
`opaque(...)` codec is not-ready but valid, and a `legacy: true` card is skipped
rather than failed. Every case runs through the validator's own directory
function against a temp copy, so a bad field never has to touch a tracked card.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]
VALIDATOR = TOOLS / "atlas" / "ontology-validate.py"
SCHEMA = REPO / "research" / "atlas" / "ontology" / "schema.json"


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "ontology_validate_under_test", VALIDATOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_validator()


def concept(**overrides):
    base = {
        "uid": "msg.example",
        "kind": "message",
        "name": "ExampleMsg",
        "summary": "a conforming card for the validator's own test",
        "confidence": "layout",
        "status": "candidate",
        "evidence": [{"type": "atlas", "ref": "test"}],
        "fields": [{"name": "count", "type": "u32be", "evidence": "partial"}],
    }
    base.update(overrides)
    return base


def run(cards):
    """validate_dir over a throwaway concepts directory, one card per stem."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for stem, card in cards.items():
            (directory / f"{stem}.json").write_text(
                json.dumps(card), encoding="utf-8"
            )
        return MODULE.validate_dir(SCHEMA, directory)


class OntologyValidateTest(unittest.TestCase):
    def test_conforming_card_is_ready(self):
        lines, code = run({"msg.conforming": concept()})
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "OK msg.conforming  ready")

    def test_invented_codec_fails(self):
        bad = concept(
            fields=[{"name": "count", "type": "string", "evidence": "partial"}]
        )
        lines, code = run({"msg.invented": bad})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.invented"))
        self.assertIn("string", lines[0])

    def test_opaque_codec_is_not_ready_but_valid(self):
        card = concept(
            fields=[{"name": "blob", "type": "opaque(blob)", "evidence": "unknown"}]
        )
        lines, code = run({"msg.opaque": card})
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "OK msg.opaque  not-ready (1 opaque)")

    def test_legacy_card_is_skipped_not_failed(self):
        legacy = concept(
            legacy=True,
            fields=[{"name": "count", "type": "string", "evidence": "partial"}],
        )
        lines, code = run({"msg.legacy": legacy})
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("LEGACY msg.legacy"))

    def test_prefixed_codec_after_prefix_varint_fails(self):
        # FIX 1: prefixed_bytes/prefixed_string INCLUDE their length prefix, so a
        # standalone prefix_varint field right before one double-counts the prefix.
        card = concept(
            fields=[
                {"name": "length", "type": "prefix_varint", "evidence": "partial"},
                {"name": "blob", "type": "prefixed_bytes", "evidence": "partial"},
            ]
        )
        lines, code = run({"msg.double_count": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.double_count"))
        self.assertIn("prefixed_bytes", lines[0])

    def test_prefixed_codec_without_prefix_varint_is_ready(self):
        card = concept(
            fields=[
                {
                    "name": "blob",
                    "type": "prefixed_bytes",
                    "evidence": "partial",
                    "max": 512,
                }
            ]
        )
        lines, code = run({"msg.prefixed_only": card})
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "OK msg.prefixed_only  ready")

    def test_envelope_named_field_fails(self):
        # FIX 2: the record envelope is framing, never a fields[] item.
        card = concept(
            fields=[
                {
                    "name": "typed_header",
                    "type": "opaque(typed_header)",
                    "evidence": "measured",
                }
            ]
        )
        lines, code = run({"msg.envelope": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.envelope"))
        self.assertIn("envelope", lines[0])

    def test_envelope_note_fails(self):
        card = concept(
            fields=[
                {
                    "name": "head",
                    "type": "opaque(head)",
                    "evidence": "measured",
                    "note": "Measured 00 01 a4 02: the typed envelope, the prefix varint 0xa4.",
                }
            ]
        )
        lines, code = run({"msg.envelope_note": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.envelope_note"))

    def test_envelope_rule_reaches_legacy_cards(self):
        card = concept(
            legacy=True,
            fields=[
                {
                    "name": "typed_header",
                    "type": "opaque(typed_header)",
                    "evidence": "measured",
                }
            ],
        )
        lines, code = run({"msg.legacy_envelope": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.legacy_envelope"))

    def test_fieldless_card_is_neither_ready_nor_not_ready(self):
        lines, code = run({"msg.fieldless": concept(fields=[])})
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "OK msg.fieldless  field-less")

    def test_summary_splits_fielded_and_fieldless(self):
        lines, code = run(
            {
                "msg.fielded": concept(
                    fields=[{"name": "count", "type": "u32be", "evidence": "partial"}]
                ),
                "msg.fieldless": concept(uid="msg.fieldless", fields=[]),
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[-1],
            "summary: 2 cards (fielded 1, field-less 1); "
            "fielded codegen-ready: 1/1; 0 opaque fields",
        )


if __name__ == "__main__":
    unittest.main()
