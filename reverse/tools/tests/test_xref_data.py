"""Data/code xref scanner tests (stdlib unittest).

`python ef.py re xref xrefs --needle <hex>` only indexes *code* targets
(call/jump destinations), so it reports "not found" for a vtable slot or a
string. `pe/xref-data.py` answers the missing question: every site that
references a target VA, as an absolute 64-bit pointer in `.rdata`/`.data`
(vtable entries, pointer tables) or as a RIP-relative displacement in `.text`.

These tests run against a synthetic PE built in a temp directory, so they never
read the installed client. They pin the two things that make the scanner useful:
a known `lea reg,[rip+disp]` is reported at its exact site (and its containing
instruction VA), and a known 8-byte pointer-table entry is reported in its
section. An off-by-one displacement and an absent target must stay unfound.
"""

from __future__ import annotations

import importlib.util
import pathlib
import struct
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "pe", "corpus"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SPEC = importlib.util.spec_from_file_location(
    "xref_data", ROOT / "pe" / "xref-data.py"
)
xref_data = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = xref_data
_SPEC.loader.exec_module(xref_data)


IMAGE_BASE = 0x140000000
TEXT_VA, TEXT_RAW, TEXT_RSIZE = 0x1000, 0x400, 0x400
RDATA_VA, RDATA_RAW, RDATA_RSIZE = 0x2000, 0x800, 0x200
DATA_VA, DATA_RAW, DATA_RSIZE = 0x3000, 0xA00, 0x100
SECTION_HEADER_OFF = 0x188


def _section_header(name: str, vaddr: int, vsize: int, raw: int, rsize: int) -> bytes:
    header = bytearray(40)
    header[0 : len(name)] = name.encode()
    # catalog.PE reads `<IIII` -> (vsize, vaddr, rsize, raw).
    struct.pack_into("<IIII", header, 8, vsize, vaddr, rsize, raw)
    return bytes(header)


def build_pe() -> bytes:
    """A minimal PE32+ whose section map catalog.PE can read."""
    buf = bytearray(DATA_RAW + DATA_RSIZE)
    struct.pack_into("<I", buf, 0x3C, 0x80)  # e_lfanew
    buf[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", buf, 0x84, 0x8664)  # Machine
    struct.pack_into("<H", buf, 0x86, 3)  # NumberOfSections
    struct.pack_into("<H", buf, 0x94, 240)  # SizeOfOptionalHeader
    struct.pack_into("<H", buf, 0x98, 0x20B)  # PE32+ magic
    struct.pack_into("<Q", buf, 0xB0, IMAGE_BASE)  # ImageBase
    off = SECTION_HEADER_OFF
    for name, vaddr, vsize, raw, rsize in (
        (".text", TEXT_VA, TEXT_RSIZE, TEXT_RAW, TEXT_RSIZE),
        (".rdata", RDATA_VA, RDATA_RSIZE, RDATA_RAW, RDATA_RSIZE),
        (".data", DATA_VA, DATA_RSIZE, DATA_RAW, DATA_RSIZE),
    ):
        buf[off : off + 40] = _section_header(name, vaddr, vsize, raw, rsize)
        off += 40
    return bytes(buf)


def text_va(foff: int) -> int:
    return IMAGE_BASE + TEXT_VA + (foff - TEXT_RAW)


def put_lea(buf: bytearray, foff: int, target: int) -> None:
    """Write `48 8d 05 <disp32>` at file offset foff, resolving to target."""
    disp = target - (text_va(foff) + 7)
    buf[foff : foff + 3] = b"\x48\x8d\x05"
    struct.pack_into("<i", buf, foff + 3, disp)


class XrefDataScan(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xref-data-")
        self.addCleanup(self._tmp.cleanup)
        self.target = IMAGE_BASE + RDATA_VA + 0x10
        self.lea_foff = TEXT_RAW + 0x20
        self.rdata_ptr_foff = RDATA_RAW + 0x10
        self.data_ptr_foff = DATA_RAW + 0x40

        buf = bytearray(build_pe())
        put_lea(buf, self.lea_foff, self.target)
        struct.pack_into("<Q", buf, self.rdata_ptr_foff, self.target)
        struct.pack_into("<Q", buf, self.data_ptr_foff, self.target)
        # A decoy pointer one byte low must not be reported.
        struct.pack_into("<Q", buf, RDATA_RAW + 0x80, self.target + 1)
        path = pathlib.Path(self._tmp.name) / "synthetic.exe"
        path.write_bytes(bytes(buf))
        self.pe = xref_data.PE(path)

    def test_reports_exactly_the_known_sites(self) -> None:
        hits = xref_data.scan(self.pe, self.target)
        expected = [
            xref_data.Hit("code", ".text", text_va(self.lea_foff + 3), text_va(self.lea_foff)),
            xref_data.Hit("data", ".rdata", IMAGE_BASE + RDATA_VA + 0x10, None),
            xref_data.Hit("data", ".data", IMAGE_BASE + DATA_VA + 0x40, None),
        ]
        self.assertEqual(hits, expected)

    def test_pointer_in_data_section_is_reported(self) -> None:
        kinds = {h.kind for h in xref_data.scan(self.pe, self.target)}
        sections = {h.section for h in xref_data.scan(self.pe, self.target)}
        self.assertEqual(kinds, {"data", "code"})
        self.assertEqual(sections, {".text", ".rdata", ".data"})

    def test_absent_target_has_no_hits(self) -> None:
        self.assertEqual(xref_data.scan(self.pe, self.target + 0x1000), [])

    def test_off_by_one_displacement_is_not_a_hit(self) -> None:
        # The decoy pointer sits at target+1; it must not resolve to the target.
        hits = xref_data.scan(self.pe, self.target + 1)
        self.assertEqual(hits, [xref_data.Hit("data", ".rdata", IMAGE_BASE + RDATA_VA + 0x80, None)])

    def test_scan_many_shares_one_pass(self) -> None:
        result = xref_data.scan_many(self.pe, [self.target, self.target + 0x1000])
        self.assertEqual(len(result[self.target]), 3)
        self.assertEqual(result[self.target + 0x1000], [])


if __name__ == "__main__":
    unittest.main()
