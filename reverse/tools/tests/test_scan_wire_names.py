"""Wire-type-name scan tests (stdlib unittest).

`research/derived/wire-type-names.json` is the only place a wire number becomes a
type name, and every downstream protocol conclusion reads it. Three properties
have to survive a client build move:

* the name really is the printable run that the GUID belongs to. A brace-wrapped
  GUID may sit between the two (`PingMsg\\0{85C7E01E-...}\\0\\0<guid>`), so taking the
  nearest run verbatim names a type after a GUID;
* one name belongs to one GUID. The `.rdata` form `<name>\\0<pad>\\0<GUID1>\\0<GUID2>`
  gives both GUIDs the same name, and the second claimant must stay unnamed rather
  than carry a confident wrong name;
* the build pin still matches the image. GUID strings are build-scoped, and the
  hand-verified anchors exist precisely so a stale pin cannot silently rename the
  table.

Synthetic images keep these tests independent of the installed game, and no test
reads the game executable.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SPEC = importlib.util.spec_from_file_location(
    "scan_wire_names", ROOT / "type" / "scan-wire-names.py"
)
wire = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = wire
_SPEC.loader.exec_module(wire)

GUID_A = "6a379fb80bdd43a1ab3e9843d7be8cd3"
GUID_B = "767fc9bf1c8d417fad19c51e363d4df0"
BRACE_GUID = "85c7e01e-55de-4a6e-afc5-80fa9a8ad260"


def dashed(guid: str) -> str:
    """The lowercase dashed form the image stores and typeindex.json does not."""
    return f"{guid[0:8]}-{guid[8:12]}-{guid[12:16]}-{guid[16:20]}-{guid[20:32]}".lower()


def descriptor(name: str, guid: str, brace: str | None = None) -> bytes:
    """One `<name>\\0[<brace>\\0\\0]<dashed guid>\\0` block, 8-byte aligned.

    The brace form is UPPERCASE in the image (it is AZ's own UUID rendering), which is
    exactly why the scan's lowercase GUID pattern does not treat it as a dashed GUID.
    """
    body = name.encode() + b"\0"
    if brace is not None:
        body += b"{" + brace.upper().encode() + b"}\0\0"
    body += dashed(guid).encode() + b"\0"
    return body + b"\0" * (-len(body) % 8)


class Synthetic:
    """A synthetic image plus the type table that indexes it."""

    def __init__(self, blocks: bytes, wires: list[str]) -> None:
        self.image = b"\0" * 16 + blocks
        self.sha256 = hashlib.sha256(self.image).hexdigest()
        self.wires = wires

    def write(self, case: unittest.TestCase, registry: dict[str, str] | None = None):
        """Materialise the image, its type table and an optional AZ registry."""
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        exe = root / "NewWorld.exe"
        exe.write_bytes(self.image)
        typeindex = root / "typeindex.json"
        typeindex.write_text(
            json.dumps({"generationTime": "synthetic", "typeIndex": self.wires}),
            encoding="utf-8",
        )
        atlas = root / "research" / "atlas"
        atlas.mkdir(parents=True, exist_ok=True)
        entries = [
            {"name": name, "guid": guid} for guid, name in (registry or {}).items()
        ]
        (atlas / "az-type-registry.json").write_text(
            json.dumps({"types": entries}), encoding="utf-8"
        )
        return root, exe, typeindex


def scan(case: unittest.TestCase, image: Synthetic, registry: dict[str, str] | None = None):
    root, exe, typeindex = image.write(case, registry)
    with mock.patch.object(wire, "ROOT", root):
        return wire.scan(exe, typeindex)


def rows(result: dict) -> dict[int, dict]:
    return {r["wire_type"]: r for r in result["names"]}


class NamingTest(unittest.TestCase):
    def test_names_a_wire_from_the_run_that_precedes_its_guid(self) -> None:
        image = Synthetic(descriptor("MovableThingMsg", GUID_A), [GUID_A])
        result = scan(self, image)
        self.assertEqual(
            rows(result)[0],
            {"wire_type": 0, "guid": dashed(GUID_A), "name": "MovableThingMsg",
             "source": "rdata"},
        )
        self.assertEqual(result["named"], 1)
        self.assertEqual(result["ambiguous_names"], 0)

    def test_skips_a_brace_wrapped_guid_between_the_name_and_the_guid(self) -> None:
        """The 349/PingMsg shape: `name\\0{other guid}\\0\\0<guid>`."""
        image = Synthetic(
            descriptor("HeartbeatMsg", GUID_A, brace=BRACE_GUID), [GUID_A]
        )
        row = rows(scan(self, image))[0]
        self.assertEqual((row["name"], row["source"]), ("HeartbeatMsg", "rdata"))

    def test_a_name_is_claimed_by_only_one_guid(self) -> None:
        """`name\\0<GUID1>` then a bare `<GUID2>`: GUID2 must stay unnamed."""
        image = Synthetic(
            descriptor("SharedNameMsg", GUID_A) + descriptor("SharedNameMsg", GUID_B),
            [GUID_A, GUID_B],
        )
        result = scan(self, image)
        by_wire = rows(result)
        self.assertEqual(by_wire[0]["name"], "SharedNameMsg")   # the adjacent one keeps it
        self.assertEqual(by_wire[0]["source"], "rdata")
        self.assertIsNone(by_wire[1]["name"])
        self.assertIsNone(by_wire[1]["source"])
        self.assertEqual(result["ambiguous_names"], 1)
        self.assertEqual(result["named"], 1)

    def test_falls_back_to_the_az_type_registry_and_records_its_source(self) -> None:
        image = Synthetic(b"", [GUID_A])
        result = scan(self, image, registry={dashed(GUID_A): "RegistryOnlyMsg"})
        row = rows(result)[0]
        self.assertEqual((row["name"], row["source"]), ("RegistryOnlyMsg", "az-registry"))

    def test_reports_a_guid_absent_from_the_image_as_unnamed(self) -> None:
        image = Synthetic(descriptor("SomeMsg", GUID_A), [GUID_A, GUID_B])
        row = rows(scan(self, image))[1]
        self.assertEqual((row["name"], row["source"]), (None, None))


class CheckTest(unittest.TestCase):
    def _result(self, name: str = "MovableThingMsg", guid: str = GUID_A) -> dict:
        return {
            "build_sha256": "a" * 64,
            "wire_types": 1,
            "named": wire.MIN_NAMED,
            "names": [
                {"wire_type": 0, "guid": dashed(guid), "name": name, "source": "rdata"}
            ],
            "ambiguous_names": 0,
        }

    def _check(self, result: dict, anchors: dict[int, str]) -> list[str]:
        with mock.patch.multiple(
            wire, BUILD_SHA256=result["build_sha256"], ANCHORS=anchors
        ):
            return wire.check(result)

    def test_accepts_a_scan_that_reproduces_the_pin_and_the_anchors(self) -> None:
        self.assertEqual(self._check(self._result(), {0: "MovableThingMsg"}), [])

    def test_rejects_a_scan_from_a_different_build(self) -> None:
        result = self._result()
        with mock.patch.multiple(wire, BUILD_SHA256="0" * 64, ANCHORS={0: "MovableThingMsg"}):
            problems = wire.check(result)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("a" * 64, problems[0])

    def test_names_the_wire_whose_anchor_stopped_reproducing(self) -> None:
        problems = self._check(self._result(), {7: "MovableThingMsg"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("wire 7 -> None", problems[0])

    def test_rejects_a_name_that_is_not_identifier_shaped(self) -> None:
        problems = self._check(self._result(name="F)@"), {0: "F)@"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not identifier-shaped", problems[0])

    def test_rejects_a_scan_that_named_almost_nothing(self) -> None:
        result = self._result()
        result["named"] = wire.MIN_NAMED - 1
        problems = self._check(result, {0: "MovableThingMsg"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("adjacency scan is probably wrong", problems[0])


class MainTest(unittest.TestCase):
    def _run(self, image: Synthetic, argv: list[str], anchors: dict[int, str]):
        root, exe, typeindex = image.write(self)
        out = root / "wire-type-names.json"
        printed: list[str] = []
        with mock.patch.multiple(
            wire,
            ROOT=root,
            BUILD_SHA256=image.sha256,
            ANCHORS=anchors,
            MIN_NAMED=1,
        ):
            with mock.patch.object(
                sys,
                "argv",
                ["scan-wire-names", *argv, "--exe", str(exe),
                 "--typeindex", str(typeindex), "--out", str(out)],
            ):
                with mock.patch.object(sys, "stdout", _Sink(printed)):
                    code = wire.main()
        return code, "\n".join(printed), out

    def test_writes_the_table_when_the_pin_and_the_anchors_hold(self) -> None:
        image = Synthetic(descriptor("MovableThingMsg", GUID_A), [GUID_A])
        code, printed, out = self._run(image, ["--check"], {0: "MovableThingMsg"})
        self.assertEqual(code, 0, printed)
        self.assertIn("wire types 1, named 1", printed)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["build_sha256"], image.sha256)
        self.assertEqual(written["named"], 1)

    def test_refuses_to_write_on_a_build_it_is_not_pinned_to(self) -> None:
        image = Synthetic(descriptor("MovableThingMsg", GUID_A), [GUID_A])
        root, exe, typeindex = image.write(self)
        out = root / "wire-type-names.json"
        printed: list[str] = []
        with mock.patch.multiple(
            wire, ROOT=root, BUILD_SHA256="0" * 64, ANCHORS={}, MIN_NAMED=1
        ):
            with mock.patch.object(
                sys,
                "argv",
                ["scan-wire-names", "--check", "--exe", str(exe),
                 "--typeindex", str(typeindex), "--out", str(out)],
            ):
                with mock.patch.object(sys, "stdout", _Sink(printed)):
                    code = wire.main()
        self.assertEqual(code, 1)
        self.assertFalse(out.is_file())
        self.assertIn("build sha256", "\n".join(printed))
        self.assertIn("refusing to write", "\n".join(printed))

    def test_reports_the_problem_but_still_writes_without_check(self) -> None:
        """Unchanged behaviour: `--check` is the only thing that gates the write."""
        image = Synthetic(descriptor("MovableThingMsg", GUID_A), [GUID_A])
        code, printed, out = self._run(image, [], {0: "WrongNameMsg"})
        self.assertEqual(code, 0, printed)
        self.assertIn("INVARIANT FAILED: wire 0 -> 'MovableThingMsg'", printed)
        self.assertTrue(out.is_file())


class CommittedArtifactTest(unittest.TestCase):
    """The committed table must describe the build the tool is pinned to."""

    def setUp(self) -> None:
        path = ROOT.parents[2] / "research" / "derived" / "wire-type-names.json"
        self.artifact = json.loads(path.read_text(encoding="utf-8"))

    def test_the_pin_matches_the_committed_artifact(self) -> None:
        self.assertEqual(self.artifact["build_sha256"], wire.BUILD_SHA256)

    def test_the_committed_artifact_still_answers_for_every_anchor(self) -> None:
        by_wire = {r["wire_type"]: r for r in self.artifact["names"]}
        for wire_type, want in wire.ANCHORS.items():
            row = by_wire[wire_type]
            self.assertEqual(row["name"], want, f"wire {wire_type}")
            self.assertIn(row["source"], ("rdata", "az-registry"), f"wire {wire_type}")

    def test_the_committed_artifact_covers_the_whole_type_table(self) -> None:
        typeindex = json.loads(
            (ROOT.parents[2] / "private-client" / "runtime" / "typeindex.json")
            .read_text(encoding="utf-8")
        )["typeIndex"]
        self.assertEqual(self.artifact["wire_types"], len(typeindex))


class _Sink:
    """A writable stand-in for sys.stdout that keeps what was printed."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self._pending = ""

    def write(self, text: str) -> int:
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self.lines.append(line)
        return len(text)

    def flush(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
