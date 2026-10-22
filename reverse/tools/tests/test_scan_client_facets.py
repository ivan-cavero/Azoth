"""Facet-factory scan tests (stdlib unittest).

The scan is the only thing that turns "a client facet exists" into "this function
constructs it", so two properties have to survive every client build:

* the five-word table tail is matched exactly. The four shared slots are function
  pointers in `.text`; when they move, the scan must report zero tables and
  refuse to write instead of building a table out of a lookalike;
* the class name is read out of the factory body with the standard library only.
  The harness virtualenv ships no Capstone, and a name that stops resolving used
  to degrade into a silently dropped row.

Synthetic PE images keep these tests independent of the installed game.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalog import PE  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "scan_client_facets", ROOT / "scan-client-facets.py"
)
facets = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = facets
_SPEC.loader.exec_module(facets)

IMAGE_BASE = 0x140000000
TEXT_VA = 0x140001000
RDATA_VA = 0x140003000
TEXT_END = TEXT_VA + 0x200

NAME = "TestWidgetComponentClientFacet"
NAME_VA = RDATA_VA + 0x100
DECOY = "SomeOtherString"
DECOY_VA = RDATA_VA + 0x180

# Four shared slots plus one factory, all inside the synthetic .text.
SHARED = (TEXT_VA + 0x40, TEXT_VA + 0x50, TEXT_VA + 0x60, TEXT_VA + 0x70)
FACTORY = TEXT_VA + 0x80
OTHER_FACTORY = TEXT_VA + 0x90
TAIL = (SHARED[0], SHARED[1], None, SHARED[2], SHARED[3])


def build_image(text: bytes, rdata: bytes) -> bytes:
    """A two-section PE32+ image that `catalog.PE` can parse."""
    e_lfanew, opt_size = 0x40, 0xF0
    headers = bytearray(0x400)
    struct.pack_into("<I", headers, 0x3C, e_lfanew)
    headers[e_lfanew : e_lfanew + 4] = b"PE\0\0"
    struct.pack_into("<H", headers, e_lfanew + 6, 2)  # number of sections
    struct.pack_into("<H", headers, e_lfanew + 20, opt_size)
    struct.pack_into("<Q", headers, e_lfanew + 24 + 24, IMAGE_BASE)
    table = e_lfanew + 24 + opt_size
    for i, (name, va, raw) in enumerate(
        ((b".text", TEXT_VA, 0x400), (b".rdata", RDATA_VA, 0x600))
    ):
        o = table + i * 40
        headers[o : o + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIII", headers, o + 8, 0x200, va - IMAGE_BASE, 0x200, raw)
    return bytes(headers) + text.ljust(0x200, b"\0") + rdata.ljust(0x200, b"\0")


def lea_rip(site: int, target: int, reg: int = 2) -> bytes:
    """`lea r<N>, [rip+disp32]`: seven bytes, how a factory passes the name."""
    return bytes((0x48, 0x8D, ((reg & 7) << 3) | 0x05)) + struct.pack(
        "<i", target - (site + 7)
    )


def mov_rip(site: int, target: int, reg: int = 0) -> bytes:
    """`mov r<N>, [rip+disp32]`: seven bytes, a pointer load, not a string."""
    return bytes((0x48, 0x8B, ((reg & 7) << 3) | 0x05)) + struct.pack(
        "<i", target - (site + 7)
    )


def tail(factory: int, shared: tuple[int, int, int, int] = SHARED) -> bytes:
    """The five-word descriptor tail, factory in slot 2."""
    return struct.pack("<5Q", shared[0], shared[1], factory, shared[2], shared[3])


class SyntheticImage:
    """A synthetic client image: table tails in .rdata, code in .text."""

    def __init__(
        self, tables: list[tuple[int, bytes]], code: dict[int, bytes] | None = None
    ) -> None:
        rdata = bytearray(b"\0" * 0x200)
        for offset, words in tables:
            rdata[offset : offset + len(words)] = words
        o = NAME_VA - RDATA_VA
        rdata[o : o + len(NAME) + 1] = NAME.encode() + b"\0"
        o = DECOY_VA - RDATA_VA
        rdata[o : o + len(DECOY) + 1] = DECOY.encode() + b"\0"
        text = bytearray(b"\xCC" * 0x200)
        for va, body in (code or {}).items():
            start = va - TEXT_VA
            text[start : start + len(body)] = body
        self.data = build_image(bytes(text), bytes(rdata))
        self.sha256 = hashlib.sha256(self.data).hexdigest()


def open_pe(case: unittest.TestCase, image: SyntheticImage) -> tuple[PE, pathlib.Path]:
    """Write the synthetic image to a temp dir outside the worktree and parse it."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    exe = pathlib.Path(tmp.name) / "NewWorld.exe"
    exe.write_bytes(image.data)
    return PE(exe), exe


class TailScanTest(unittest.TestCase):
    def test_finds_the_factory_of_a_matching_five_word_tail(self) -> None:
        image = SyntheticImage([(0x40, tail(FACTORY))])
        pe, _ = open_pe(self, image)
        with mock.patch.object(facets, "TAIL", TAIL):
            self.assertEqual(
                facets.find_tables(pe, (TEXT_VA, TEXT_END)),
                [(RDATA_VA + 0x40, FACTORY)],
            )

    def test_finds_every_table_when_a_class_owns_two(self) -> None:
        image = SyntheticImage(
            [(0x40, tail(FACTORY)), (0x80, tail(OTHER_FACTORY))]
        )
        pe, _ = open_pe(self, image)
        with mock.patch.object(facets, "TAIL", TAIL):
            self.assertEqual(
                facets.find_tables(pe, (TEXT_VA, TEXT_END)),
                [(RDATA_VA + 0x40, FACTORY), (RDATA_VA + 0x80, OTHER_FACTORY)],
            )

    def test_a_factory_outside_text_is_not_a_facet_table(self) -> None:
        image = SyntheticImage([(0x40, tail(DECOY_VA))])
        pe, _ = open_pe(self, image)
        with mock.patch.object(facets, "TAIL", TAIL):
            self.assertEqual(facets.find_tables(pe, (TEXT_VA, TEXT_END)), [])

    def test_a_moved_shared_word_yields_no_table(self) -> None:
        """The 1.460 regression: the four shared slots are build-scoped."""
        image = SyntheticImage([(0x40, tail(FACTORY, (SHARED[0], SHARED[1], SHARED[2], SHARED[3])))])
        pe, _ = open_pe(self, image)
        moved = (SHARED[0], SHARED[1], None, SHARED[2], SHARED[3] + 8)
        with mock.patch.object(facets, "TAIL", moved):
            self.assertEqual(facets.find_tables(pe, (TEXT_VA, TEXT_END)), [])

    def test_tail_presence_names_the_words_that_are_gone(self) -> None:
        image = SyntheticImage([(0x40, tail(FACTORY))])
        pe, _ = open_pe(self, image)
        with mock.patch.object(facets, "TAIL", TAIL):
            self.assertEqual(
                [present for _, present in facets.tail_presence(pe)],
                [True, True, True, True],
            )
        with mock.patch.object(
            facets, "TAIL", (SHARED[0], SHARED[1], None, SHARED[2] + 8, SHARED[3])
        ):
            self.assertEqual(
                facets.tail_presence(pe),
                [
                    (SHARED[0], True),
                    (SHARED[1], True),
                    (SHARED[2] + 8, False),
                    (SHARED[3], True),
                ],
            )


class ResolveNameTest(unittest.TestCase):
    def test_reads_the_name_the_factory_loads_with_lea(self) -> None:
        image = SyntheticImage(
            [], {FACTORY: lea_rip(FACTORY, NAME_VA)}
        )
        pe, _ = open_pe(self, image)
        self.assertEqual(facets.resolve_name(pe, FACTORY), NAME)

    def test_prefers_the_client_facet_name_over_an_earlier_string(self) -> None:
        image = SyntheticImage(
            [],
            {FACTORY: lea_rip(FACTORY, DECOY_VA) + lea_rip(FACTORY + 7, NAME_VA)},
        )
        pe, _ = open_pe(self, image)
        self.assertEqual(facets.resolve_name(pe, FACTORY), NAME)

    def test_resolves_without_a_third_party_disassembler(self) -> None:
        image = SyntheticImage([], {FACTORY: mov_rip(FACTORY, NAME_VA)})
        pe, _ = open_pe(self, image)
        with mock.patch.dict(sys.modules, {"capstone": None}):
            self.assertEqual(facets.resolve_name(pe, FACTORY), NAME)


class DiagnosisAndRefusalTest(unittest.TestCase):
    def _run(
        self, image: SyntheticImage, anchors, tail_words, argv: list[str]
    ) -> tuple[int, str, pathlib.Path]:
        """Run `main()` on a synthetic exe and return (exit code, output, out path)."""
        _, exe = open_pe(self, image)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = pathlib.Path(tmp.name) / "facets.json"
        printed: list[str] = []
        with mock.patch.multiple(
            facets,
            TAIL=tail_words,
            ANCHORS=anchors,
            BUILD_SHA256=image.sha256,
            EXPECTED_TABLES=1,
            EXPECTED_DISTINCT=1,
        ):
            with mock.patch.object(
                sys, "argv", ["scan-client-facets", *argv, "--exe", str(exe), "--out", str(out)]
            ):
                with mock.patch.object(sys, "stdout", _Sink(printed)):
                    code = facets.main()
        return code, "\n".join(printed), out

    def test_reports_the_recovered_count_and_writes_the_table(self) -> None:
        image = SyntheticImage(
            [(0x40, tail(FACTORY))], {FACTORY: lea_rip(FACTORY, NAME_VA)}
        )
        code, printed, out = self._run(image, {NAME: (FACTORY,)}, TAIL, ["--check"])
        self.assertEqual(code, 0, printed)
        self.assertIn("tables=1 named=1", printed)
        self.assertEqual(
            json.loads(out.read_text(encoding="utf-8")),
            {
                "build_sha256": image.sha256,
                "facets": [
                    {
                        "table": hex(RDATA_VA + 0x40),
                        "factory": hex(FACTORY),
                        "name": NAME,
                    }
                ],
            },
        )

    def test_refuses_to_write_and_names_the_moved_tail_word(self) -> None:
        image = SyntheticImage([(0x40, tail(FACTORY))], {FACTORY: lea_rip(FACTORY, NAME_VA)})
        moved = (SHARED[0], SHARED[1], None, SHARED[2] + 8, SHARED[3])
        code, printed, out = self._run(image, {NAME: (FACTORY,)}, moved, ["--check"])
        self.assertEqual(code, 1)
        self.assertFalse(out.is_file())
        self.assertIn("INVARIANT FAILED: 0 tables, expected 1", printed)
        self.assertIn("tables=0 named=0", printed)
        self.assertIn(f"shared tail word 0x{SHARED[2] + 8:x} is absent", printed)
        self.assertIn("refusing to write", printed)

    def test_rejects_a_scan_from_a_different_build(self) -> None:
        image = SyntheticImage(
            [(0x40, tail(FACTORY))], {FACTORY: lea_rip(FACTORY, NAME_VA)}
        )
        result = {
            "build_sha256": "0" * 64,
            "facets": [
                {"table": hex(RDATA_VA + 0x40), "factory": hex(FACTORY), "name": NAME}
            ],
        }
        with mock.patch.multiple(
            facets,
            BUILD_SHA256=image.sha256,
            ANCHORS={NAME: (FACTORY,)},
            EXPECTED_TABLES=1,
            EXPECTED_DISTINCT=1,
        ):
            problems = facets.check(result)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("0" * 64, problems[0])


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
