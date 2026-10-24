"""AZ type registry scan tests (stdlib unittest).

`research/atlas/az-type-registry.json` is the GUID-to-name map that names wire
types when the `.rdata` adjacency route cannot, so a wrong pairing here silently
renames a protocol type everywhere downstream. Two properties have to survive a
client build move:

* the 1.400 form is read verbatim. `<name>\\0<NUL padding>{GUID}` produced 4781
  entries on 1.460 and every one of them must keep coming back;
* the 1.460 form -- the same descriptor with the record's field block, a run of
  in-image pointers, between the name and the brace -- is read ONLY when the
  interstice is a real field block. Measured 2026-10-22: the 1.460 image pairs
  `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems` with
  {AA0A0B64-...} across six pointer qwords (file offsets 0x8137680 and
  0x81376f0), while a loose backward walk in the pointer-dense embedded-data
  tables pairs the asset name `FxScriptsData` with an unrelated {7E27B9BC-...}
  across 331 qwords. A candidate that cannot be told apart from the second case
  must be left out, not guessed.

Synthetic images keep these tests independent of the installed game, and no test
reads the game executable or git history.
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
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SPEC = importlib.util.spec_from_file_location("scan_az_types", ROOT / "type" / "scan-az-types.py")
az = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = az
_SPEC.loader.exec_module(az)

IMAGE_BASE = 0x140000000
RDATA_VA = IMAGE_BASE + 0x400   # payload[0] is also the .rdata VA
GUID_A = "aa0a0b64-475a-4828-a050-7b1a3f045493"
GUID_B = "6a379fb8-0bdd-43a1-ab3e-9843d7be8cd3"
# Field-block entries are plain in-image addresses; the header area is inside the
# image and always present, so a synthetic record never has to grow to hold them.
POINTERS = [IMAGE_BASE + 0x100 + 8 * i for i in range(8)]


def brace(guid: str) -> bytes:
    """The uuid literal as AZ stores it: uppercase, brace-wrapped, NUL padded."""
    return b"{" + guid.upper().encode() + b"}\0\0"


def block(name: bytes, words: int, tail: bytes | None = None) -> bytes:
    """`<name>\\0<pad to 8>` + `words` pointer qwords + `{GUID}` + `\\0\\0`."""
    body = name + b"\0"
    body += b"\0" * (-len(body) % 8)
    body += b"".join(struct.pack("<Q", POINTERS[i % len(POINTERS)]) for i in range(words))
    body += tail if tail is not None else brace(GUID_A)
    return body + b"\0" * (-len(body) % 8)


def descriptor(name: str, guid: str = GUID_A, words: int = 0) -> bytes:
    """One record for `name`, `words` pointer qwords before its brace GUID."""
    return block(name.encode(), words, brace(guid))


def image(*blocks: bytes) -> bytes:
    """A PE32+ image whose `.rdata` holds `blocks` from offset 0."""
    payload = b"".join(blocks)
    e_lfanew, opt_size = 0x40, 0xF0
    headers = bytearray(0x400)
    struct.pack_into("<I", headers, 0x3C, e_lfanew)
    headers[e_lfanew : e_lfanew + 4] = b"PE\0\0"
    struct.pack_into("<H", headers, e_lfanew + 6, 1)
    struct.pack_into("<H", headers, e_lfanew + 20, opt_size)
    struct.pack_into("<Q", headers, e_lfanew + 24 + 24, IMAGE_BASE)
    table = e_lfanew + 24 + opt_size
    headers[table : table + 8] = b".rdata".ljust(8, b"\0")
    struct.pack_into(
        "<IIII",
        headers,
        table + 8,
        len(payload),
        RDATA_VA - IMAGE_BASE,
        len(payload),
        0x400,
    )
    return bytes(headers) + payload.ljust(0x200, b"\0")


def scan(*blocks: bytes) -> dict[str, list[str]]:
    """Run the scanner over a synthetic image, returning name -> [guid]."""
    data = image(*blocks)
    return az.scan(data, IMAGE_BASE, IMAGE_BASE + len(data))


def pairs(found: dict[str, list[str]]) -> set[tuple[str, str]]:
    return {(name, guid) for name, guids in found.items() for guid in guids}


class LegacyFormTest(unittest.TestCase):
    """The 1.400 form: name, NUL padding, brace GUID. Behaviour must not change."""

    def test_reads_a_nul_padded_name_and_guid(self) -> None:
        found = scan(descriptor("MovableThing"))
        self.assertEqual(pairs(found), {("MovableThing", GUID_A)})

    def test_keeps_one_name_with_several_guids(self) -> None:
        found = scan(descriptor("Transform", GUID_A), descriptor("Transform", GUID_B))
        self.assertEqual(found["Transform"], [GUID_A, GUID_B])

    def test_still_ignores_the_untrustworthy_bare_guid_form(self) -> None:
        """No braces, no entry: the loose form pairs `Transform` with the wrong id."""
        loose = b"MovableThing\0" + GUID_A.encode() + b"\0"
        self.assertEqual(pairs(scan(loose + b"\0" * 8)), set())


class FieldBlockFormTest(unittest.TestCase):
    """The 1.460 form: `<name>\\0<pad>{<pointer qwords>}{GUID}`."""

    def test_reads_a_name_separated_from_its_guid_by_pointer_qwords(self) -> None:
        """The measured 7048 shape: six pointer qwords after the NUL padding."""
        name = "GlobalStorageComponentClientFacet_ReceiveStorageSearchItems"
        self.assertEqual(pairs(scan(descriptor(name, words=6))), {(name, GUID_A)})

    def test_accepts_the_measured_maximum_field_block(self) -> None:
        found = scan(descriptor("RewardTrackComponentServerFacet_Reset", words=az.MAX_FIELD_BLOCK))
        self.assertEqual(
            pairs(found), {("RewardTrackComponentServerFacet_Reset", GUID_A)}
        )

    def test_rejects_a_block_longer_than_any_measured_descriptor(self) -> None:
        found = scan(descriptor("DataTableName", words=az.MAX_FIELD_BLOCK + 1))
        self.assertEqual(pairs(found), set())

    def test_rejects_a_filler_that_is_not_in_image_pointers(self) -> None:
        """An address outside the image, or text, is not a field block."""
        outside = struct.pack("<Q", 0xDEADBEEF)
        text = b"not a qword ptr!"  # exactly two qwords, all of them implausible
        for filler in (outside, text):
            with self.subTest(filler=filler):
                self.assertEqual(pairs(scan(block(b"SomeName", 0, filler + brace(GUID_A) + b"\0" * 8))), set())

    def test_rejects_a_name_that_is_only_the_tail_of_a_longer_string(self) -> None:
        """`Field.SomeName` must not be reported as a descriptor called `SomeName`."""
        prefix = b"\0" * 7 + b"."     # keeps the name 8-byte aligned, adds a printable head
        self.assertEqual(pairs(scan(prefix, descriptor("SomeName", words=4))), set())

    def test_rejects_a_name_that_does_not_start_on_a_record_boundary(self) -> None:
        """Descriptor names are 8-byte aligned; a 4-mod-8 run is packed data."""
        record = b"\0" * 4 + b"SomeName\0" + b"\0" * 3   # name at 4, block at 16
        record += struct.pack("<Q", POINTERS[0]) * 4 + brace(GUID_A) + b"\0" * 8
        self.assertEqual(pairs(scan(record)), set())

    def test_rejects_a_guid_or_hash_fragment_as_a_name(self) -> None:
        """Measured false pairing: `7E3497006D14` in front of a real type's GUID."""
        self.assertEqual(pairs(scan(descriptor("7E3497006D14", words=6))), set())

    def test_does_not_rename_a_guid_the_nul_form_already_named(self) -> None:
        """One GUID has one registered name; a second one is an adjacency error."""
        found = scan(descriptor("KnownType"), descriptor("OtherName", words=4))
        self.assertEqual(found["KnownType"], [GUID_A])
        self.assertNotIn("OtherName", found)


class RegistryBuildTest(unittest.TestCase):
    """`build()` and `check()` on a synthetic image and type table."""

    NAME = "GlobalStorageComponentClientFacet_ReceiveStorageSearchItems"

    def setUp(self) -> None:
        self.data = image(descriptor(self.NAME, words=6), descriptor("KnownType", GUID_B))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.exe = self.root / "NewWorld.exe"
        self.exe.write_bytes(self.data)
        runtime = self.root / "private-client" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "typeindex.json").write_text(
            json.dumps({"typeIndex": [GUID_A.upper().replace("-", ""), GUID_B.upper().replace("-", "")]}),
            encoding="utf-8",
        )

    def _build(self) -> dict:
        with mock.patch.object(az, "ROOT", self.root):
            return az.build(self.exe)

    def test_records_both_forms_and_the_wire_type_of_the_guid(self) -> None:
        payload = self._build()
        self.assertEqual(payload["build_sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(payload["names"], 2)
        self.assertEqual(payload["entries"], 2)
        self.assertEqual(payload["pointer_form_entries"], 1)
        by_name = {entry["name"]: entry for entry in payload["types"]}
        self.assertEqual(by_name["KnownType"]["wire_type"], 1)
        self.assertEqual(by_name[self.NAME]["wire_type"], 0)

    def test_own_pinned_check_passes_on_the_recovered_registry(self) -> None:
        payload = self._build()
        with mock.patch.dict(az.PINNED, {self.NAME: GUID_A, "KnownType": GUID_B}, clear=True):
            self.assertEqual(az.check(payload), 0)

    def test_pinned_check_fails_when_a_hand_verified_guid_disappears(self) -> None:
        payload = self._build()
        payload["types"] = [e for e in payload["types"] if e["name"] != "KnownType"]
        with mock.patch.dict(az.PINNED, {self.NAME: GUID_A, "KnownType": GUID_B}, clear=True):
            with mock.patch.object(sys, "stdout", _Sink()):
                self.assertEqual(az.check(payload), 1)


class _Sink:
    """A writable stand-in for sys.stdout that discards what was printed."""

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
