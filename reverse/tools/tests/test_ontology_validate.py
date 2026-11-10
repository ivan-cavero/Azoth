"""The closed-field validator's promised outcomes, on temp copies.

WHY THIS EXISTS. `reverse/tools/atlas/ontology-validate.py` is the only thing
that enforces the closed `fields` item schema in
`research/atlas/ontology/schema.json`. This test pins the outcomes the validator
promises: a conforming card is ready, an invented codec fails, an `opaque(...)`
codec is not-ready but valid, and a `legacy: true` card is skipped rather than
failed. Every case runs through the validator's own directory function against a
temp copy, so a bad field never has to touch a tracked card.

THE MEANING RULE. A field must say whether its meaning is `known` or only its
`layout-only`. This file also pins the three rules that make that honest: a field
with no `meaning` fails, a placeholder name may never claim `known`, and a
`known` field must carry a note that says what it is. Marking a field
`layout-only` is VISIBILITY, never a gate: such a card is still ready.
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


def field(name: str, type_name: str, meaning: str, note: str = None, **extra) -> dict:
    item = {
        "name": name,
        "type": type_name,
        "evidence": "partial",
        "meaning": meaning,
    }
    if note is not None:
        item["note"] = note
    item.update(extra)
    return item


def concept(**overrides):
    base = {
        "uid": "msg.example",
        "kind": "message",
        "name": "ExampleMsg",
        "summary": "a conforming card for the validator's own test",
        "confidence": "layout",
        "status": "candidate",
        "evidence": [{"type": "atlas", "ref": "test"}],
        "fields": [field("count", "u32be", "known", "the number of items")],
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
        self.assertEqual(
            lines[0], "OK msg.conforming  ready  [meaning: 1 known, 0 layout-only]"
        )

    def test_invented_codec_fails(self):
        bad = concept(fields=[field("count", "string", "known", "the count")])
        lines, code = run({"msg.invented": bad})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.invented"))
        self.assertIn("string", lines[0])

    def test_opaque_codec_is_not_ready_but_valid(self):
        card = concept(fields=[field("blob", "opaque(blob)", "layout-only")])
        lines, code = run({"msg.opaque": card})
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[0],
            "OK msg.opaque  not-ready (1 opaque)  "
            "[meaning: 0 known, 1 layout-only]",
        )

    def test_legacy_card_is_skipped_not_failed(self):
        legacy = concept(
            legacy=True,
            fields=[field("count", "string", "known", "the count")],
        )
        lines, code = run({"msg.legacy": legacy})
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("LEGACY msg.legacy"))

    def test_prefixed_codec_after_prefix_varint_fails(self):
        # FIX 1: prefixed_bytes/prefixed_string INCLUDE their length prefix, so a
        # standalone prefix_varint field right before one double-counts the prefix.
        card = concept(
            fields=[
                field("length", "prefix_varint", "known", "the prefix length"),
                field("blob", "prefixed_bytes", "layout-only"),
            ]
        )
        lines, code = run({"msg.double_count": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.double_count"))
        self.assertIn("prefixed_bytes", lines[0])

    def test_prefixed_codec_without_prefix_varint_is_ready(self):
        card = concept(
            fields=[
                field("blob", "prefixed_bytes", "layout-only", max=512),
            ]
        )
        lines, code = run({"msg.prefixed_only": card})
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[0],
            "OK msg.prefixed_only  ready  [meaning: 0 known, 1 layout-only]",
        )

    def test_envelope_named_field_fails(self):
        # FIX 2: the record envelope is framing, never a fields[] item.
        card = concept(
            fields=[field("typed_header", "opaque(typed_header)", "layout-only")]
        )
        lines, code = run({"msg.envelope": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.envelope"))
        self.assertIn("envelope", lines[0])

    def test_envelope_note_fails(self):
        card = concept(
            fields=[
                field(
                    "head",
                    "opaque(head)",
                    "layout-only",
                    note="Measured 00 01 a4 02: the typed envelope, the prefix varint 0xa4.",
                )
            ]
        )
        lines, code = run({"msg.envelope_note": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.envelope_note"))

    def test_envelope_rule_reaches_legacy_cards(self):
        card = concept(
            legacy=True,
            fields=[field("typed_header", "opaque(typed_header)", "layout-only")],
        )
        lines, code = run({"msg.legacy_envelope": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.legacy_envelope"))

    def test_literal_count_vec_is_ready(self):
        # STEP 1: `count` as a JSON integer is a literal element count on a
        # composite type and does not by itself block codegen-readiness.
        card = concept(
            fields=[field("bounds", "vec<f32be>", "known", "four world bounds", count=4)]
        )
        lines, code = run({"msg.bounds": card})
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[0], "OK msg.bounds  ready  [meaning: 1 known, 0 layout-only]"
        )

    def test_literal_count_on_non_composite_fails(self):
        # A literal count is only meaningful on vec<T>/matrix<T>; a scalar with
        # a count is a modelling error, not silently ignored.
        card = concept(fields=[field("n", "u32be", "known", "the count", count=4)])
        lines, code = run({"msg.bad_count": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.bad_count"))

    def test_fieldless_card_is_neither_ready_nor_not_ready(self):
        lines, code = run({"msg.fieldless": concept(fields=[])})
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[0],
            "OK msg.fieldless  field-less  [meaning: 0 known, 0 layout-only]",
        )

    def test_summary_splits_fielded_and_fieldless(self):
        lines, code = run(
            {
                "msg.fielded": concept(
                    fields=[field("count", "u32be", "known", "the number of items")]
                ),
                "msg.fieldless": concept(uid="msg.fieldless", fields=[]),
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[-2],
            "summary: 2 cards (fielded 1, field-less 1); "
            "fielded codegen-ready: 1/1; 0 opaque fields; "
            "fields: 1 known, 0 layout-only",
        )

    def test_last_line_states_the_outcome(self):
        """`tail -1` must never read green when a card FAILed.

        MEASURED 2026-11-09: two FAILs were committed while every check was read
        through `tail -1`, because the summary was the last line and said nothing
        about failures. The outcome sentence is therefore last, and it counts
        FAILs and LEGACY skips explicitly.
        """
        ok_lines, _ = run({"msg.fine": concept(fields=[field("n", "u32be", "known", "x")])})
        self.assertEqual(ok_lines[-1], "result: ok (0 FAIL, 0 LEGACY of 1 cards)")

        bad_lines, bad_code = run(
            {"msg.broken": concept(fields=[{"name": "n", "type": "u32be", "evidence": "partial"}])}
        )
        self.assertEqual(bad_code, 1)
        self.assertEqual(bad_lines[-1], "result: FAILED (1 FAIL, 0 LEGACY of 1 cards)")
        self.assertTrue(
            bad_lines[-2].startswith("summary:"),
            "the census must sit immediately above the outcome sentence",
        )

    def test_a_legacy_skip_is_counted_not_hidden(self):
        """A LEGACY line is a skip, so it must appear in the outcome sentence.

        `legacy: true` is a deliberate exemption, not a pass. Counting it beside
        FAILs keeps the exemption visible instead of letting it vanish into `ok`.
        """
        card = {"uid": "msg.old", "kind": "msg", "legacy": True, "fields": []}
        lines, code = run({"msg.old": card})
        self.assertEqual(code, 0)
        self.assertEqual(lines[0].split("  ")[0], "LEGACY msg.old (0 fields unvalidated)")
        self.assertEqual(lines[-1], "result: ok (0 FAIL, 1 LEGACY of 1 cards)")

    # --- the meaning rule --------------------------------------------------

    def test_missing_meaning_fails(self):
        card = concept(
            fields=[{"name": "count", "type": "u32be", "evidence": "partial"}]
        )
        lines, code = run({"msg.no_meaning": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.no_meaning"))
        self.assertIn("meaning", lines[0])

    def test_placeholder_claiming_known_fails(self):
        # field_a is a placeholder name: it may never claim `known`.
        card = concept(fields=[field("field_a", "u64be", "known", "an actor id")])
        lines, code = run({"msg.placeholder_known": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.placeholder_known"))
        self.assertIn("layout-only", lines[0])

    def test_known_without_a_note_fails(self):
        card = concept(fields=[field("actor_id", "u64be", "known", note="")])
        lines, code = run({"msg.known_no_note": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.known_no_note"))
        self.assertIn("note", lines[0])

    def test_layout_only_field_is_still_ready(self):
        # Marking is visibility, never a gate: a layout-only field does not make
        # the card un-codegen-ready.
        card = concept(fields=[field("field_a", "u64be", "layout-only")])
        lines, code = run({"msg.visible": card})
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[0], "OK msg.visible  ready  [meaning: 0 known, 1 layout-only]"
        )

    def test_meaning_rule_reaches_legacy_cards(self):
        card = concept(
            legacy=True,
            fields=[{"name": "first", "type": "u64be", "evidence": "unknown"}],
        )
        lines, code = run({"msg.legacy_no_meaning": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL msg.legacy_no_meaning"))
        self.assertIn("meaning", lines[0])

    # --- the presence, nested, counted and optional constructs ---------------

    def presence(self, **overrides) -> dict:
        base = {
            "group": {"name": "group_mask", "bits": 8},
            "member": {"name": "entry_mask", "bits": 7, "continuation": 128},
        }
        base.update(overrides)
        return base

    def presence_card(self, fields=None, **overrides) -> dict:
        if fields is None:
            fields = [
                field(
                    "activeObjectives",
                    "nested(codec.example-item)",
                    "known",
                    "the active set",
                    presence={"group": 1, "member": 3},
                )
            ]
        return concept(fields=fields, **{"presence": self.presence(), **overrides})

    def test_presence_masked_card_is_ready(self):
        lines, code = run(
            {
                "codec.example": self.presence_card(),
                "codec.example-item": concept(
                    uid="codec.example-item",
                    kind="codec",
                    fields=[field("item_id", "u64be", "known", "the item id")],
                ),
            }
        )
        self.assertEqual(code, 0)
        self.assertIn("OK codec.example  ready", " ".join(lines))

    def test_presence_member_without_coordinates_fails(self):
        card = self.presence_card(
            fields=[field("active", "u64be", "known", "the active set")]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))
        self.assertIn("presence", lines[0])

    def test_presence_coordinates_without_a_mask_fail(self):
        card = concept(
            fields=[
                field(
                    "active",
                    "u64be",
                    "known",
                    "the active set",
                    presence={"group": 1, "member": 3},
                )
            ]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))
        self.assertIn("presence", lines[0])

    def test_presence_index_beyond_a_single_byte_mask_fails(self):
        # No continuation, so the member level is exactly one seven-bit byte and a
        # member index at or above `bits` has no byte to live in.
        card = self.presence_card(
            presence={
                "group": {"name": "group_mask", "bits": 8},
                "member": {"name": "entry_mask", "bits": 7},
            },
            fields=[
                field(
                    "active",
                    "u64be",
                    "known",
                    "the active set",
                    presence={"group": 1, "member": 7},
                )
            ],
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))
        self.assertIn("member", lines[0])

    def test_presence_index_wide_of_one_byte_needs_a_continuation(self):
        # The same member index 7 is legal once the level declares a continuation:
        # it lands in the second mask byte of the sequence.
        card = self.presence_card(
            fields=[
                field(
                    "active",
                    "u64be",
                    "known",
                    "the active set",
                    presence={"group": 1, "member": 7},
                )
            ]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 0)
        self.assertIn("OK codec.example  ready", " ".join(lines))

    def test_a_wide_member_level_of_twenty_members_is_ready(self):
        # Twenty seven-bit members span three mask bytes; the continuation makes
        # every index 0..19 representable, so the card is valid and ready.
        card = self.presence_card(
            fields=[
                field(
                    f"m{index}",
                    "u8",
                    "layout-only",
                    presence={"group": 0, "member": index},
                )
                for index in range(20)
            ]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 0)
        self.assertIn("OK codec.example  ready", " ".join(lines))

    def test_duplicate_presence_coordinates_fail(self):
        card = self.presence_card(
            fields=[
                field(
                    "active_set",
                    "u64be",
                    "known",
                    "a member",
                    presence={"group": 1, "member": 3},
                ),
                field(
                    "completed_set",
                    "u64be",
                    "known",
                    "another member",
                    presence={"group": 1, "member": 3},
                ),
            ]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))
        self.assertIn("duplicate", lines[0])

    def test_continuation_bit_must_sit_above_the_member_bits(self):
        card = self.presence_card(
            presence={
                "group": {"name": "group_mask", "bits": 8},
                "member": {"name": "entry_mask", "bits": 6, "continuation": 128},
            }
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))
        self.assertIn("continuation", lines[0])

    def test_nested_reference_must_name_a_codec_card(self):
        card = self.presence_card()
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))
        self.assertIn("codec.example-item", lines[0])

    def test_counted_element_must_be_a_vocabulary_member(self):
        card = concept(
            fields=[
                field(
                    "items",
                    "counted(string)",
                    "known",
                    "a counted run of names",
                )
            ]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))

    def test_optional_element_must_be_a_vocabulary_member(self):
        card = concept(
            fields=[
                field("maybe", "optional(string)", "known", "an optional name")
            ]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))

    def test_memory_field_cannot_declare_wire_presence(self):
        card = self.presence_card(
            fields=[
                field(
                    "active",
                    "u64be",
                    "known",
                    "the active set",
                    where="memory",
                    presence={"group": 1, "member": 3},
                )
            ]
        )
        lines, code = run({"codec.example": card})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL codec.example"))

    def test_placeholder_name_shapes(self):
        placeholder = [
            "field_a",
            "unresolved_u64",
            "unknown_thing",
            "raw_bytes",
            "blob_64",
            "head",
            "head16",
            "flags_at_0x14",
            "tail_from_0x28",
            "u32_be_1",
            "u8",
            "trailing_bool_0",
            "first",
            "second",
        ]
        for name in placeholder:
            self.assertTrue(
                MODULE._is_placeholder_name(name),
                f"{name!r} should be a placeholder",
            )
        for name in ("actor_id", "level_name", "session_nonce", "points"):
            self.assertFalse(
                MODULE._is_placeholder_name(name),
                f"{name!r} should not be a placeholder",
            )


if __name__ == "__main__":
    unittest.main()