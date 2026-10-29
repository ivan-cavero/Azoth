"""Inbound-inventory name-resolution tests (stdlib unittest).

`scripts/measure/inbound-inventory.py` used to name each wire from three registries in
order, starting with `research/derived/wire-type-names.json` -- the adjacency heuristic
`scan-wire-names.py` produces, which `research/atlas/meanings.md` documents as disproven:
of the wires both it and the client hook table name, 620 disagree. The tool must read the
verified table `research/derived/message-names.json` (the client's own hook-record name)
first, keep the adjacency table only for a wire the verified table does not name, and then
consult the Javelin and AZ registries as last resorts for a wire neither table names.

Synthetic tables keep the test independent of the installed client: the four shapes are
built here and `_wire_names` / `_load_names` are called on them directly. Set
`INBOUND_INVENTORY` to another module path to run this file against a different revision
of the tool.
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
_JAVELIN = 0x30
_AZ = 0x31

ADJACENCY_TABLE = {
    "names": [
        {"wire_type": _DISAGREE, "guid": "d61428c7-6d83-4dcc-b28c-705c6ce16c8a",
         "source": "rdata", "name": "PaperdollComponentServerFacet_UnequipAllItems"},
        {"wire_type": _FALLBACK, "guid": "ebb62a4f-b2c4-4510-9549-b2ea09c85c63",
         "source": "rdata", "name": "FallbackComponentClientFacet_OnlyOld"},
        {"wire_type": _NEITHER, "guid": "b42b3e49-b674-405c-a6ad-0cc5a8e368ba",
         "source": None, "name": None},
        {"wire_type": _JAVELIN, "guid": "11111111-1111-1111-1111-111111111111",
         "source": None, "name": None},
        {"wire_type": _AZ, "guid": "22222222-2222-2222-2222-222222222222",
         "source": None, "name": None},
    ]
}
VERIFIED_TABLE = {
    "rows": [
        {"wire": "0x1743",
         "names": [{"name": "PlayerComponentServerFacet_DebugSetMatchId"}]},
        {"wire": "0x10", "names": []},
        {"wire": "0x20", "names": []},
        {"wire": "0x30", "names": []},
        {"wire": "0x31", "names": []},
    ]
}
# The two last-resort registries. Each also tries to name a wire a table already named, so
# the tests can prove the tables still win.
JAVELIN_TABLE = {
    "messages": [
        {"name": "JavelinFallbackMsg",
         "guid": "11111111-1111-1111-1111-111111111111", "wire_type": _JAVELIN},
        {"name": "JavelinShouldNotWin",
         "guid": "d61428c7-6d83-4dcc-b28c-705c6ce16c8a", "wire_type": _DISAGREE},
        {"name": "JavelinShouldNotWinFallback",
         "guid": "ebb62a4f-b2c4-4510-9549-b2ea09c85c63", "wire_type": _FALLBACK},
    ]
}
AZ_TABLE = {
    "types": [
        {"name": "AzFallbackType", "guid": "22222222-2222-2222-2222-222222222222"},
        # Also names _JAVELIN's GUID, to prove javelin wins over az on the same wire.
        {"name": "AzShouldLoseToJavelin",
         "guid": "11111111-1111-1111-1111-111111111111"},
        {"name": "AzShouldNotWin", "guid": "d61428c7-6d83-4dcc-b28c-705c6ce16c8a"},
    ]
}


def _resolve(adjacency: dict, verified: dict, javelin: dict, az: dict) -> dict:
    """Load four synthetic tables through the tool's single `_load_names` entry point."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for key, table in (("adjacency", adjacency), ("verified", verified),
                           ("javelin", javelin), ("az", az)):
            path = pathlib.Path(tmp) / f"{key}.json"
            path.write_text(json.dumps(table), encoding="utf-8")
            paths[key] = path
        return inbound_inventory._load_names(
            path=paths["adjacency"], verified_path=paths["verified"],
            javelin_path=paths["javelin"], az_path=paths["az"])


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
        return _resolve(ADJACENCY_TABLE, VERIFIED_TABLE, {}, {})

    def test_unnamed_wire_keeps_its_guid_and_verified_name_overrides(self) -> None:
        rows = self._rows()
        self.assertEqual(rows[_NEITHER]["guid"],
                         "b42b3e49-b674-405c-a6ad-0cc5a8e368ba")
        self.assertIsNone(rows[_NEITHER]["name"])
        self.assertEqual(rows[_DISAGREE]["name"],
                         "PlayerComponentServerFacet_DebugSetMatchId")


class LastResortRegistryTest(unittest.TestCase):
    """The javelin and az registries are restored as last-resort name sources.

    They only name a wire the verified and adjacency tables leave unnamed, and a row's
    `source` still labels the registry that named it.
    """

    def test_a_wire_only_javelin_names_keeps_its_name_and_source_label(self) -> None:
        rows = _resolve(ADJACENCY_TABLE, VERIFIED_TABLE, JAVELIN_TABLE, AZ_TABLE)
        self.assertEqual(rows[_JAVELIN]["name"], "JavelinFallbackMsg")
        self.assertEqual(rows[_JAVELIN]["source"], "javelin-registry")

    def test_a_wire_only_az_names_keeps_its_name_and_source_label(self) -> None:
        rows = _resolve(ADJACENCY_TABLE, VERIFIED_TABLE, JAVELIN_TABLE, AZ_TABLE)
        self.assertEqual(rows[_AZ]["name"], "AzFallbackType")
        self.assertEqual(rows[_AZ]["source"], "az-registry")

    def test_the_tables_still_win_over_the_last_resort_registries(self) -> None:
        rows = _resolve(ADJACENCY_TABLE, VERIFIED_TABLE, JAVELIN_TABLE, AZ_TABLE)
        self.assertEqual(rows[_DISAGREE]["name"],
                         "PlayerComponentServerFacet_DebugSetMatchId")
        self.assertEqual(rows[_FALLBACK]["name"],
                         "FallbackComponentClientFacet_OnlyOld")
        self.assertEqual(rows[_DISAGREE]["source"], "rdata")
        self.assertEqual(rows[_FALLBACK]["source"], "rdata")

    def test_a_wire_no_source_names_keeps_a_null_name(self) -> None:
        rows = _resolve(ADJACENCY_TABLE, VERIFIED_TABLE, JAVELIN_TABLE, AZ_TABLE)
        self.assertIsNone(rows[_NEITHER]["name"])
        self.assertIsNone(rows[_NEITHER]["source"])


if __name__ == "__main__":
    unittest.main()
