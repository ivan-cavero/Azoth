"""Inbound-inventory name-resolution tests (stdlib unittest).

`scripts/measure/inbound-inventory.py` used to name each wire from three registries in
order, starting with `research/derived/wire-type-names.json` -- the adjacency heuristic
`scan-wire-names.py` produces, which `research/atlas/meanings.md` documents as disproven:
of the wires both it and the client hook table name, 620 disagree. The tool must read the
verified table `research/derived/message-names.json` (the client's own hook-record name)
first, keeping the adjacency table only for a wire the verified table does not name.

Synthetic tables keep the test independent of the installed client: the two shapes are
built here and `_wire_names` is called on them directly. Set `INBOUND_INVENTORY` to another
module path to run this file against a different revision of the tool.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
MODULE = pathlib.Path(
    os.environ.get("INBOUND_INVENTORY",
                   REPO / "scripts" / "measure" / "inbound-inventory.py"))

# The tool loads azoth_world from the world source tree; make that importable whether the
# module under test lives in the repo or in a scratch copy outside it.
sys.path.insert(0, str(REPO / "services" / "world" / "src"))

_SPEC = importlib.util.spec_from_file_location("inbound_inventory", MODULE)
inbound_inventory = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = inbound_inventory
_SPEC.loader.exec_module(inbound_inventory)

# Wire 0x1743 is a measured disagreement carried verbatim from the real tables: the
# adjacency table names it after a neighbouring Paperdoll message, while the hook table
# names it from its own registration record.
_DISAGREE = 0x1743
_FALLBACK = 0x10
_NEITHER = 0x20

ADJACENCY_TABLE = {
    "names": [
        {"wire_type": _DISAGREE, "guid": "d61428c7-6d83-4dcc-b28c-705c6ce16c8a",
         "source": "rdata", "name": "PaperdollComponentServerFacet_UnequipAllItems"},
        {"wire_type": _FALLBACK, "guid": "ebb62a4f-b2c4-4510-9549-b2ea09c85c63",
         "source": "rdata", "name": "FallbackComponentClientFacet_OnlyOld"},
        {"wire_type": _NEITHER, "guid": "b42b3e49-b674-405c-a6ad-0cc5a8e368ba",
         "source": None, "name": None},
    ]
}
VERIFIED_TABLE = {
    "rows": [
        {"wire": "0x1743",
         "names": [{"name": "PlayerComponentServerFacet_DebugSetMatchId"}]},
        {"wire": "0x10", "names": []},
        {"wire": "0x20", "names": []},
    ]
}


class NameSourceTest(unittest.TestCase):
    def test_verified_name_wins_over_the_disproven_adjacency_name(self) -> None:
        names = inbound_inventory._wire_names(ADJACENCY_TABLE, VERIFIED_TABLE)
        self.assertEqual(
            names[_DISAGREE], "PlayerComponentServerFacet_DebugSetMatchId"
        )
        # The wire's old adjacency name must not leak in at all.
        self.assertNotIn("UnequipAllItems", names.values())

    def test_falls_back_to_the_adjacency_table_for_a_wire_verified_does_not_name(
        self,
    ) -> None:
        self.assertEqual(
            inbound_inventory._wire_names(ADJACENCY_TABLE, VERIFIED_TABLE)[_FALLBACK],
            "FallbackComponentClientFacet_OnlyOld",
        )

    def test_a_wire_neither_table_names_contributes_nothing(self) -> None:
        names = inbound_inventory._wire_names(ADJACENCY_TABLE, VERIFIED_TABLE)
        self.assertNotIn(_NEITHER, names)
        self.assertEqual(set(names), {_DISAGREE, _FALLBACK})


class PreserveRowShapeTest(unittest.TestCase):
    """PRESERVE: `_load_names` still returns {name, source, guid} per wire."""

    def _rows(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            adjacency = pathlib.Path(tmp) / "wire-type-names.json"
            verified = pathlib.Path(tmp) / "message-names.json"
            adjacency.write_text(json.dumps(ADJACENCY_TABLE), encoding="utf-8")
            verified.write_text(json.dumps(VERIFIED_TABLE), encoding="utf-8")
            return inbound_inventory._load_names(path=adjacency, verified_path=verified)

    def test_unnamed_wire_keeps_its_guid_and_verified_name_overrides(self) -> None:
        rows = self._rows()
        self.assertEqual(rows[_NEITHER]["guid"],
                         "b42b3e49-b674-405c-a6ad-0cc5a8e368ba")
        self.assertIsNone(rows[_NEITHER]["name"])
        self.assertEqual(rows[_DISAGREE]["name"],
                         "PlayerComponentServerFacet_DebugSetMatchId")


if __name__ == "__main__":
    unittest.main()
