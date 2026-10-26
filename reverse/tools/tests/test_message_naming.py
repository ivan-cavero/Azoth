"""The naming tie-breaker: one table row per lambda, not eight qwords from the base.

WHY THIS FILE EXISTS. `message-names.py` names a wire type by walking the client's
registration hook backwards. It used to read eight consecutive qwords from the
registration table and treat each as a descriptor of the type being named. A table
holds many rows, so that reports the neighbours' types too, and 796 of the 7,052
wire types came out with two or more names for one GUID -- 23% of everything the
tool named.

The fix is structural rather than statistical: the row that owns a registration
lambda is the row whose first qword IS that lambda, and that row's own descriptor
is its second qword. This file pins the three things that make it trustworthy
instead of merely tidy:

  1. it still gets the two hand-proven controls right;
  2. it is right on every replay type whose name is known independently;
  3. it never takes a name away -- when the row layout does not apply it returns
     nothing and the old slot scan is used, so the fallback is what protects the
     2,594 types that were already unambiguous.

The third point is the one worth protecting. Uniqueness is easy to achieve by
picking a wrong-but-consistent row, which would have looked like success.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]


def load_tool():
    sys_path_added = [str(TOOLS), str(TOOLS / "type")]
    import sys

    for entry in sys_path_added:
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location(
        "message_names_under_test", TOOLS / "type" / "message-names.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exe_available() -> bool:
    try:
        from common import default_paths

        return Path(default_paths()["exe"]).is_file()
    except Exception:
        return False


@unittest.skipUnless(exe_available(), "New World install not present on this machine")
class TieBreakerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from common import default_paths
        from peutil import PEx

        cls.mn = load_tool()
        cls.px = PEx(default_paths()["exe"])
        cls.pe = cls.px.pe
        cls.calls = cls.mn.call_map(cls.pe)
        cls.leas = cls.mn.lea_map(cls.pe)
        cls.index = cls.mn.load_index()

    def resolve(self, wire):
        return self.mn.resolve(self.px, self.calls, self.leas, wire, self.index)

    def test_both_hand_proven_controls_still_resolve(self):
        """0x663 and 0x65c were proven before this tool existed; it must not regress them."""
        for wire, want in ((0x663, "LevelInfoChangedMsg"),
                           (0x65C, "PlayerManagerSelfIdentificationMsg")):
            row = self.resolve(wire)
            got = [n["name"] for n in row["names"]]
            self.assertEqual(got, [want], f"0x{wire:x} -> {got}")

    def test_the_controls_are_single_answers_not_first_of_several(self):
        """The ambiguous answer for 0x663 used to include `State`; it must not now."""
        row = self.resolve(0x663)
        self.assertEqual(len(row["names"]), 1)
        self.assertIn("State", row.get("candidates") or [], "the alias should still be recorded")

    def test_replay_types_with_independent_names_are_correct(self):
        """Ground truth from research/derived/replay-type-names.json.

        These seven are the replay types the old method called ambiguous, i.e.
        exactly the ones a tie-breaker has to get right. Their `name` field is the
        independently established answer, and 0x663's is proven by decompiling its
        handler rather than by this tool.
        """
        path = REPO / "research" / "derived" / "replay-type-names.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = 0
        for entry in data["types"]:
            if not entry.get("ambiguous"):
                continue
            row = self.resolve(int(entry["wire"], 16))
            got = row["names"][0]["name"] if row["names"] else None
            self.assertEqual(got, entry["name"], f"{entry['wire']} -> {got}")
            checked += 1
        self.assertGreaterEqual(checked, 7, "the fixture should still hold the ambiguous cases")

    def test_an_unrelated_address_has_no_entry(self):
        """entry_descriptor answers about a specific lambda, not about any pointer."""
        row = self.resolve(0x663)
        name = row["names"][0]
        record, lam = int(name["record"], 16), int(name["lambda"], 16)
        self.assertEqual(
            self.mn.entry_descriptor(self.pe, record, lam), int(name["thunk"], 16) & 0xFFFFFFFFFFFFFFFF
        )
        # A value that is not a lambda in that table must not match a neighbouring row.
        self.assertIsNone(self.mn.entry_descriptor(self.pe, record, 0xDEADBEEF))

    def test_previously_unambiguous_names_are_never_dropped(self):
        """The fallback is load-bearing: 18 types miss the row match and keep the slot scan.

        Checks a sample rather than all 2,594 so the suite stays fast, but a
        failure here means the tie-breaker started overriding real answers.
        """
        path = REPO / "research" / "derived" / "message-names.json"
        if not path.is_file():
            self.skipTest("derived artifact not regenerated yet")
        data = json.loads(path.read_text(encoding="utf-8"))
        single = [
            r for r in data["rows"]
            if r.get("result") == "named" and len(r.get("names", [])) == 1
        ]
        self.assertTrue(single)
        for row in single[:: max(1, len(single) // 40)]:
            got = self.resolve(int(row["wire"], 16))
            self.assertEqual(
                [n["name"] for n in got["names"]],
                [row["names"][0]["name"]],
                f"{row['wire']} lost its name",
            )


if __name__ == "__main__":
    unittest.main()
