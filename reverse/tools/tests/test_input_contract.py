"""Input-contract registry tests (stdlib unittest).

`re input-contract` joins the client's input bindings to the message registry, and it
used to read `research/derived/wire-type-names.json` for the wire -> name mapping. That
table is produced by the adjacency heuristic `scan-wire-names.py`, which
`research/atlas/meanings.md` documents as disproven: of the wires both it and the client
hook table name, 620 disagree. The verified table `research/derived/message-names.json`
carries the client's own hook-record name, so the registry must read THAT, keeping the
old table only for a wire the verified table does not name.

Synthetic tables keep the test independent of the installed client: the two shapes are
built here and `load_registry` is called on them directly.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SPEC = importlib.util.spec_from_file_location(
    "input_contract", ROOT / "pak" / "input-contract.py"
)
input_contract = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = input_contract
_SPEC.loader.exec_module(input_contract)

# Wire 0x1743 is a measured disagreement carried verbatim from the real tables: the
# adjacency table names it after a neighbouring Paperdoll message, while the hook table
# names it from its own registration record.
_DISAGREE = 0x1743
_FALLBACK = 0x10
_NEITHER = 0x20

OLD_TABLE = {
    "names": [
        {"wire_type": _DISAGREE,
         "name": "PaperdollComponentServerFacet_UnequipAllItems"},
        {"wire_type": _FALLBACK, "name": "FallbackComponentClientFacet_OnlyOld"},
        {"wire_type": _NEITHER, "name": None},
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


class RegistrySourceTest(unittest.TestCase):
    def _registry(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            old = pathlib.Path(tmp) / "wire-type-names.json"
            verified = pathlib.Path(tmp) / "message-names.json"
            old.write_text(json.dumps(OLD_TABLE), encoding="utf-8")
            verified.write_text(json.dumps(VERIFIED_TABLE), encoding="utf-8")
            return input_contract.load_registry(path=old, verified_path=verified)

    def test_verified_name_wins_over_the_disproven_adjacency_name(self) -> None:
        registry = self._registry()
        self.assertEqual(
            registry["Player"]["server"],
            [{"wire_type": "0x1743", "method": "DebugSetMatchId",
              "name": "PlayerComponentServerFacet_DebugSetMatchId"}],
        )
        # The wire's old adjacency name must not leak in under its own family.
        self.assertNotIn("Paperdoll", registry)

    def test_falls_back_to_the_old_table_for_a_wire_the_verified_table_does_not_name(
        self,
    ) -> None:
        registry = self._registry()
        self.assertEqual(
            registry["Fallback"]["client"],
            [{"wire_type": "0x10", "method": "OnlyOld",
              "name": "FallbackComponentClientFacet_OnlyOld"}],
        )

    def test_a_wire_neither_table_names_contributes_nothing(self) -> None:
        self.assertEqual(set(self._registry()), {"Player", "Fallback"})


if __name__ == "__main__":
    unittest.main()
