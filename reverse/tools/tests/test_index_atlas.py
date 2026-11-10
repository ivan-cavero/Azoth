"""The index regenerator, and the drift it closes that no gate caught.

WHY THIS EXISTS. `research/atlas/ontology/indexes/{by-uid,by-kind,by-wire}.json`
were hand-maintained, and `scripts/check/check-atlas.py` checks them in only
ONE direction per index. MEASURED 2026-11-10: `by-wire` is checked for dangling
entries only, so a wire id absent from it is never reported; the atlas grew from
82 to 103 cards on 2026-11-09 and 23 wire ids went unlisted while every local
check read green. These tests pin the two things that make that stop: the
regenerator derives every index from the concept files, and `--check` fails on
drift in either direction.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check" / "index-atlas.py"


def load():
    spec = importlib.util.spec_from_file_location("index_atlas_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load()


def card(uid: str, kind: str = "message", wire_id=None) -> dict:
    entry = {
        "uid": uid,
        "kind": kind,
        "name": "Example",
        "summary": "an index test card",
        "confidence": "layout",
        "status": "candidate",
        "evidence": [{"type": "atlas", "ref": "test"}],
    }
    if wire_id is not None:
        entry["wire"] = {"id": wire_id, "direction": "S2C", "transport": "rep"}
    return entry


class IndexRegeneration(unittest.TestCase):
    def build(self, cards: list[dict]) -> dict:
        by_uid = {c["uid"]: c for c in cards}
        return MODULE.build(by_uid)

    def test_by_uid_lists_every_card(self):
        cards = [card("msg.a"), card("msg.b"), card("codec.c", kind="codec")]
        out = self.build(cards)["by-uid.json"]
        self.assertEqual(out["uids"], ["codec.c", "msg.a", "msg.b"])

    def test_by_kind_groups_by_the_cards_own_kind(self):
        cards = [
            card("msg.a"),
            card("msg.b"),
            card("codec.c", kind="codec"),
            card("codec.d", kind="codec"),
        ]
        kinds = self.build(cards)["by-kind.json"]["kinds"]
        self.assertEqual(kinds, {"codec": ["codec.c", "codec.d"], "message": ["msg.a", "msg.b"]})

    def test_by_wire_uses_the_cards_own_spelling(self):
        """The index keeps the card's spelling; cards mix hex, decimal and symbolic ids.

        A normalising index would have to decide that "663" and "0x663" are the
        same wire, and the existing entries are already mixed, so the regenerator
        copies the card verbatim and a reader compares against one spelling.
        """
        cards = [
            card("msg.hex", wire_id="0x16a0"),
            card("msg.dec", wire_id=663),
            card("flow.cmd", kind="flow", wire_id="carrier-cmd-1"),
        ]
        wires = self.build(cards)["by-wire.json"]["wires"]
        self.assertEqual(
            wires, {"0x16a0": "msg.hex", "663": "msg.dec", "carrier-cmd-1": "flow.cmd"}
        )

    def test_a_card_without_a_wire_is_absent_from_by_wire(self):
        cards = [card("msg.a"), card("msg.b", wire_id="0x1")]
        wires = self.build(cards)["by-wire.json"]["wires"]
        self.assertNotIn("msg.a", wires.values())

    def test_two_cards_claiming_one_wire_are_refused(self):
        """A duplicate wire id is a modelling defect, not a tie to break.

        The regenerator cannot pick a winner: both cards would be valid alone.
        """
        with self.assertRaises(SystemExit) as caught:
            self.build([card("msg.a", wire_id="0x1"), card("msg.b", wire_id="0x1")])
        self.assertIn("0x1", str(caught.exception))

    def test_index_drift_is_reported_when_a_card_is_unlisted_or_a_stale_uid_remains(self):
        """`--check` must catch both directions, not just the dangling one.

        MEASURED 2026-11-10: 21 uids were missing from `by-uid` and 23 wire ids
        from `by-wire`, and CI stayed green for 51 runs because only the dangling
        direction was ever checked.
        """
        with tempfile.TemporaryDirectory() as tmp:
            concepts = Path(tmp) / "concepts"
            indexes = Path(tmp) / "indexes"
            concepts.mkdir()
            indexes.mkdir()
            (concepts / "msg.a.json").write_text(json.dumps(card("msg.a")), encoding="utf-8")
            (concepts / "msg.b.json").write_text(json.dumps(card("msg.b")), encoding="utf-8")
            # Seed an index that knows only msg.a, then stale in the other direction.
            (indexes / "by-uid.json").write_text(
                json.dumps({"generated": "x", "uids": ["msg.a", "msg.ghost"]}),
                encoding="utf-8",
            )
            (indexes / "by-kind.json").write_text(
                json.dumps({"generated": "x", "kinds": {"message": ["msg.a", "msg.ghost"]}}),
                encoding="utf-8",
            )
            (indexes / "by-wire.json").write_text(
                json.dumps({"generated": "x", "wires": {}}), encoding="utf-8"
            )
            code = run_main(concepts, indexes, check=True)
            self.assertEqual(code, 1)


def run_main(concepts: Path, indexes: Path, *, check: bool) -> int:
    """main() against a temporary pair, without touching the tracked indexes."""
    import subprocess
    import sys

    script = (
        "import importlib.util as u, sys\n"
        "spec = u.spec_from_file_location('m', sys.argv[1])\n"
        "m = u.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "m.CONCEPTS = __import__('pathlib').Path(sys.argv[2])\n"
        "m.INDEXES = __import__('pathlib').Path(sys.argv[3])\n"
        "sys.argv = ['x'] + sys.argv[4:]\n"
        "raise SystemExit(m.main())\n"
    )
    args = ["--check"] if check else []
    proc = subprocess.run(
        [sys.executable, "-c", script, str(SCRIPT), str(concepts), str(indexes), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode


class TrackedTreeIsCurrent(unittest.TestCase):
    def test_the_committed_indexes_match_the_committed_cards(self):
        """The repo itself must pass `index-atlas --check`.

        This is the assertion that would have failed on 2026-11-09 while every
        other local check passed.
        """
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
