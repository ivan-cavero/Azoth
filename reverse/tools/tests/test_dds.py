"""DDS -> PNG decoder tests (stdlib unittest).

The decoder has to turn a New World UI `.dds` into a valid PNG without Pillow or
numpy, so the only trustworthy check is bytes: synthetic DDS blobs with a known
format and known block bytes, decoded to exact RGBA8 pixels, then wrapped in a
PNG whose header carries the dimensions.

The four formats that actually occur under `lyshineui/` are exercised by
construction: an uncompressed DX10 R8G8B8A8 sprite, a BC1 (DXT1) block, a BC3
(DXT5) block, and -- because New World ships BC7 -- a BC7 block whose mode 6
layout is written out bit by bit. A truncated/unsupported blob must raise and
its CLI must exit nonzero without writing a file.
"""

from __future__ import annotations

import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _kind in ("", "corpus", "pe", "type", "pak", "wire", "eac", "ops"):
    _p = str(ROOT if _kind == "" else ROOT / _kind)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dds  # noqa: E402

SCRIPT = ROOT / "pak" / "dds.py"


def make_dx10(dxgi: int, width: int, height: int, data: bytes, mips: int = 1) -> bytes:
    """A DX10 DDS: `DDS ` + 124-byte header + 20-byte DX10 header + payload."""
    header = struct.pack("<7I", 124, 0x81007, height, width, len(data), 0, mips)
    header += b"\0" * 44
    pixel_format = struct.pack("<8I", 32, 0x4, struct.unpack("<I", b"DX10")[0],
                               0, 0, 0, 0, 0)
    header += pixel_format + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    dx10 = struct.pack("<5I", dxgi, 3, 0, 1, 0)
    return b"DDS " + header + dx10 + data


def make_fourcc(fourcc: bytes, width: int, height: int, data: bytes,
                mips: int = 1) -> bytes:
    """A legacy-`FourCC` DDS (DXT1/DXT5/...): `DDS ` + 124-byte header + payload."""
    header = struct.pack("<7I", 124, 0x81007, height, width, len(data), 0, mips)
    header += b"\0" * 44
    pixel_format = struct.pack("<8I", 32, 0x4, struct.unpack("<I", fourcc)[0],
                               0, 0, 0, 0, 0)
    header += pixel_format + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    return b"DDS " + header + data


# A BC1/BC3 colour block: endpoint red (F800) and green (07E0), indices
# 0,1,2,3 repeated on every row. The three interpolants are exact.
COLOR_BLOCK = struct.pack("<HH", 0xF800, 0x07E0) + bytes([0xE4, 0xE4, 0xE4, 0xE4])
COLOR_ROW = [(255, 0, 0, 255), (0, 255, 0, 255), (170, 85, 0, 255), (85, 170, 0, 255)]


def color_expected() -> list[tuple[int, int, int, int]]:
    return COLOR_ROW * 4


class Bc1Test(unittest.TestCase):
    def test_four_colour_block_decodes_to_known_pixels(self) -> None:
        blob = make_fourcc(b"DXT1", 4, 4, COLOR_BLOCK)
        image = dds.decode(blob)
        self.assertEqual((image.width, image.height), (4, 4))
        self.assertEqual(image.format, "BC1")
        self.assertEqual(image.pixels(), color_expected())

    def test_three_colour_mode_makes_index_three_transparent(self) -> None:
        block = struct.pack("<HH", 0x0000, 0xFFFF) + bytes([0xE4] * 4)
        image = dds.decode(make_fourcc(b"DXT1", 4, 4, block))
        self.assertEqual(image.pixels()[0], (0, 0, 0, 255))
        self.assertEqual(image.pixels()[1], (255, 255, 255, 255))
        self.assertEqual(image.pixels()[2], (127, 127, 127, 255))
        self.assertEqual(image.pixels()[3], (0, 0, 0, 0))


class Bc3Test(unittest.TestCase):
    def test_alpha_and_colour_block_decodes_to_known_pixels(self) -> None:
        # alpha0=255, alpha1=0, all alpha indices 0 -> every pixel opaque.
        alpha = bytes([255, 0, 0, 0, 0, 0, 0, 0])
        image = dds.decode(make_fourcc(b"DXT5", 4, 4, alpha + COLOR_BLOCK))
        self.assertEqual(image.format, "BC3")
        self.assertEqual(image.pixels(), color_expected())

    def test_explicit_alpha_indices_change_alpha_only(self) -> None:
        # alpha0=0, alpha1=255, all indices 7 -> alpha 255; colour stays black.
        alpha = bytes([0, 255]) + bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        image = dds.decode(make_fourcc(b"DXT5", 4, 4, alpha + bytes(8)))
        self.assertEqual(image.pixels()[0], (0, 0, 0, 255))


class UncompressedTest(unittest.TestCase):
    def test_rgba8_2x2_decodes_to_exact_pixels(self) -> None:
        source = [
            (1, 2, 3, 4), (5, 6, 7, 8),
            (9, 10, 11, 12), (13, 14, 15, 16),
        ]
        payload = b"".join(bytes(px) for px in source)
        image = dds.decode(make_dx10(28, 2, 2, payload))
        self.assertEqual((image.width, image.height), (2, 2))
        self.assertEqual(image.format, "RGBA8")
        self.assertEqual(image.pixels(), source)


class Bc7Test(unittest.TestCase):
    def test_mode6_block_decodes_to_known_pixels(self) -> None:
        # Mode 6: 7-bit RGB/A endpoints, one shared p-bit per endpoint, 4-bit
        # indices. Endpoint 0 = (128, 0, 0, 255), endpoint 1 = (0, 0, 0, 255).
        bits = 0
        pos = 0

        def put(value: int, width: int):
            nonlocal bits, pos
            bits |= (value & ((1 << width) - 1)) << pos
            pos += width

        put(1 << 6, 7)  # mode 6: six zero bits then a 1
        # 7-bit endpoints; p-bit 0 makes the extended 8-bit value v<<1 exactly.
        r0, g0, b0, a0 = 64, 0, 0, 127   # -> (128, 0, 0, 254)
        r1, g1, b1, a1 = 0, 0, 0, 0
        for channel in (r0, r1, g0, g1, b0, b1, a0, a1):
            put(channel, 7)
        put(0, 1)  # p-bit for endpoint 0
        put(0, 1)  # p-bit for endpoint 1
        for _ in range(16):
            put(0, 4)  # every pixel index 0 -> endpoint 0
        block = bits.to_bytes(16, "little")
        image = dds.decode(make_dx10(98, 4, 4, block))
        self.assertEqual(image.format, "BC7")
        self.assertEqual(image.pixels(), [(128, 0, 0, 254)] * 16)


class PngTest(unittest.TestCase):
    def test_png_has_signature_and_ihdr_dimensions(self) -> None:
        payload = bytes([1, 2, 3, 4] * 4)
        png = dds.png_bytes(2, 2, dds.decode(make_dx10(28, 2, 2, payload)).pixels())
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(png[12:16], b"IHDR")
        width, height = struct.unpack(">II", png[16:24])
        self.assertEqual((width, height), (2, 2))
        self.assertIn(b"IDAT", png)
        self.assertTrue(png.endswith(b"IEND\xaeB`\x82"))


class FailureTest(unittest.TestCase):
    def test_truncated_header_raises(self) -> None:
        with self.assertRaises(ValueError):
            dds.decode(b"DDS " + b"\0" * 10)

    def test_unsupported_dxgi_format_raises(self) -> None:
        blob = make_dx10(1, 2, 2, bytes(64))  # R32G32B32A32_FLOAT
        with self.assertRaises(ValueError):
            dds.decode(blob)

    def test_cli_fails_closed_without_writing_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "bad.dds"
            source.write_bytes(make_dx10(1, 4, 4, bytes(256)))
            out = pathlib.Path(tmp) / "bad.png"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "decode-file", str(source),
                 "--out", str(out)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(out.exists())


class SelftestTest(unittest.TestCase):
    def test_absent_index_skips_gracefully(self) -> None:
        missing = pathlib.Path(tempfile.gettempdir()) / "definitely-absent-pakindex.db"
        self.assertEqual(dds.selftest(db_path=missing), 0)


if __name__ == "__main__":
    unittest.main()
