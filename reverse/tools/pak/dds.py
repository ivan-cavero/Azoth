#!/usr/bin/env python3
r"""Decode a New World UI `.dds` texture to PNG with the standard library only.

WHY THIS EXISTS
===============
The LyShine UI pipeline (`odd/tasks/lyshine-ui.md`, tasks T5) turns a sprite into
something a preview can show. `lyshineui/` in `DataStrm*.pak` holds 54,334 `.dds`
entries, all method-15 payloads decoded by `pakread.read_entry`; those bytes are
standard DDS (the `DDS ` magic, a DDS_HEADER and a pixel format). A sprite is a
PNG once the base mip is decoded, but Pillow and numpy are not available (pip is
banned in this repo), so this tool parses the header, decodes the base level to
RGBA8, and writes the PNG itself with `struct` + `zlib`.

WHAT IT SUPPORTS (measured 2026-11-01, client 1.460.6033.6024067)
================================================================
Sampling 1,007 of the 54,334 `lyshineui/*.dds` headers found five DXGI formats:
BC3 sRGB (78) dominant, BC1 sRGB (72), BC7 sRGB (99), R8G8B8A8 sRGB (29) and
R8G8B8A8 UNORM (28). This decoder handles uncompressed 32-bit (RGBA/BGRA),
BC1, BC2, BC3, BC4, BC5 and BC7, and refuses anything else. It decodes the base
level (mip 0) only.

BC7 is the only complicated one: eight block modes with per-mode subset counts,
endpoint widths and index widths. The tables below (partition patterns, anchor
pixels, interpolation weights) were recovered by probing the block layout; they
are pinned, not guessed.

WHERE THE OUTPUT GOES (S5, `docs/LEGAL.md`)
===========================================
Extracted texture PNGs are private artifacts and must never enter the repo. With
no `--out` the PNG lands under `.azoth/tmp/` (gitignored); anywhere else needs an
explicit `--out`.

Usage:
    python ef.py re dds decode <pak> <entry> [--out FILE.png]
    python ef.py re dds decode-file <in.dds> [--out FILE.png]
    python ef.py re dds selftest
"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402

PIXEL_FORMAT = {
    28: "RGBA8", 29: "RGBA8",
    87: "BGRA8", 88: "BGRA8",
    71: "BC1", 72: "BC1",
    74: "BC2", 75: "BC2",
    77: "BC3", 78: "BC3",
    80: "BC4", 81: "BC4",
    82: "BC5", 83: "BC5",
    98: "BC7", 99: "BC7",
}

FOURCC_FORMAT = {
    b"DXT1": "BC1",
    b"DXT3": "BC2",
    b"DXT5": "BC3",
    b"ATI1": "BC4", b"BC4U": "BC4",
    b"ATI2": "BC5", b"BC5U": "BC5",
}

BLOCK_BYTES = {"BC1": 8, "BC2": 16, "BC3": 16, "BC4": 8, "BC5": 16, "BC7": 16}
UNCOMPRESSED = {"RGBA8", "BGRA8"}


# --- BC7 tables (recovered from the block layout; see module docstring) ------

# 2-subset partitions: bit i of the mask is set when pixel i is in subset 1.
BC7_PART2 = (
    0xCCCC, 0x8888, 0xEEEE, 0xECC8, 0xC880, 0xFEEC, 0xFEC8, 0xEC80,
    0xC800, 0xFFEC, 0xFE80, 0xE800, 0xFFE8, 0xFF00, 0xFFF0, 0xF000,
    0xF710, 0x008E, 0x7100, 0x08CE, 0x008C, 0x7310, 0x3100, 0x8CCE,
    0x088C, 0x3110, 0x6666, 0x366C, 0x17E8, 0x0FF0, 0x718E, 0x399C,
    0xAAAA, 0xF0F0, 0x5A5A, 0x33CC, 0x3C3C, 0x55AA, 0x9696, 0xA55A,
    0x73CE, 0x13C8, 0x324C, 0x3BDC, 0x6996, 0xC33C, 0x9966, 0x0660,
    0x0272, 0x04E4, 0x4E40, 0x2720, 0xC936, 0x936C, 0x39C6, 0x639C,
    0x9336, 0x9CC6, 0x817E, 0xE718, 0xCCF0, 0x0FCC, 0x7744, 0xEE22,
)

# 3-subset partitions: masks for subset 1 and subset 2 (bit i set).
BC7_PART3_1 = (
    0x08CC, 0x8CC8, 0xCC80, 0xEC00, 0x3300, 0x00CC, 0xFF00, 0xCCCC,
    0x0F00, 0x0FF0, 0x00F0, 0x4444, 0x6666, 0x2222, 0x136C, 0x008C,
    0x36C8, 0x08CE, 0x3330, 0xF000, 0x00EE, 0x8888, 0x22C0, 0x4430,
    0x0C22, 0x0344, 0x6996, 0x9960, 0x0330, 0x0066, 0xC22C, 0x8C00,
    0x1300, 0xC400, 0x004C, 0x2222, 0x00F0, 0x2492, 0x2942, 0xC30C,
    0xC03C, 0x00AA, 0xAA00, 0x3030, 0xC0C0, 0x9090, 0xA00A, 0xAAA0,
    0x0AAA, 0xE0E0, 0x7070, 0x6660, 0x0EE0, 0x0770, 0x0666, 0x6600,
    0x0066, 0x0CC0, 0x0330, 0x6000, 0x8080, 0x1010, 0x000A, 0x08CE,
)
BC7_PART3_2 = (
    0xF600, 0x7300, 0x3310, 0x00CE, 0xCC00, 0xCC00, 0x00CC, 0x3300,
    0xF000, 0xF000, 0xFF00, 0x8888, 0x8888, 0xCCCC, 0xEC80, 0x7310,
    0xC800, 0x3100, 0xCCC0, 0x0CCC, 0xEE00, 0x7700, 0xCC00, 0x3300,
    0x00CC, 0xFC88, 0x0660, 0x6600, 0xC88C, 0xF900, 0x0CC0, 0x7310,
    0xEC80, 0x08CE, 0xEC80, 0x4444, 0x0F00, 0x4924, 0x4294, 0x0C30,
    0x03C0, 0xFF00, 0x5500, 0xCCCC, 0x0C0C, 0x6666, 0x0FF0, 0x5550,
    0xF000, 0x0E0E, 0x8888, 0x9990, 0xE00E, 0x8888, 0xF000, 0x9900,
    0xFF00, 0xC00C, 0xCCCC, 0x9000, 0x0808, 0xEEEE, 0xFFF0, 0x7310,
)

# Anchor pixel per subset: a subset's anchor stores its index with one fewer bit.
BC7_ANCHOR2 = (
    (0, 15), (0, 15), (0, 15), (0, 15), (0, 15), (0, 15), (0, 15), (0, 15),
    (0, 15), (0, 15), (0, 15), (0, 15), (0, 15), (0, 15), (0, 15), (0, 15),
    (0, 15), (0, 2), (0, 8), (0, 2), (0, 2), (0, 8), (0, 8), (0, 15),
    (0, 2), (0, 8), (0, 2), (0, 2), (0, 8), (0, 8), (0, 2), (0, 2),
    (0, 15), (0, 15), (0, 6), (0, 8), (0, 2), (0, 8), (0, 15), (0, 15),
    (0, 2), (0, 8), (0, 2), (0, 2), (0, 2), (0, 15), (0, 15), (0, 6),
    (0, 6), (0, 2), (0, 6), (0, 8), (0, 15), (0, 15), (0, 2), (0, 2),
    (0, 15), (0, 15), (0, 15), (0, 15), (0, 15), (0, 2), (0, 2), (0, 15),
)
BC7_ANCHOR3 = (
    (0, 3, 15), (0, 3, 8), (0, 8, 15), (0, 3, 15), (0, 8, 15), (0, 3, 15),
    (0, 3, 15), (0, 8, 15), (0, 8, 15), (0, 8, 15), (0, 6, 15), (0, 6, 15),
    (0, 6, 15), (0, 5, 15), (0, 3, 15), (0, 3, 8), (0, 3, 15), (0, 3, 8),
    (0, 8, 15), (0, 3, 15), (0, 3, 15), (0, 3, 8), (0, 6, 15), (0, 8, 10),
    (0, 3, 5), (0, 8, 15), (0, 6, 8), (0, 6, 10), (0, 8, 15), (0, 5, 15),
    (0, 10, 15), (0, 8, 15), (0, 8, 15), (0, 3, 15), (0, 3, 15), (0, 5, 10),
    (0, 6, 10), (0, 8, 10), (0, 8, 9), (0, 10, 15), (0, 6, 15), (0, 3, 15),
    (0, 8, 15), (0, 5, 15), (0, 3, 15), (0, 6, 15), (0, 6, 15), (0, 8, 15),
    (0, 3, 15), (0, 3, 15), (0, 5, 15), (0, 5, 15), (0, 5, 15), (0, 8, 15),
    (0, 5, 15), (0, 10, 15), (0, 5, 15), (0, 10, 15), (0, 8, 15), (0, 13, 15),
    (0, 3, 15), (0, 12, 15), (0, 3, 15), (0, 3, 8),
)

# mode: nsub, partition bits, RGB bits, alpha bits, per-endpoint p-bits,
#       shared p-bits, rotation bits, index-set widths (read order), alpha rule.
# The "alpha rule" says where alpha's index comes from: 'shared' reuses the
# colour index, 'mode4' picks between the two sets with the index-selection bit
# (which also swaps which set drives colour), 'mode5' always uses the second set.
BC7_MODES = {
    0: (3, 4, 4, 0, 1, 0, 0, (3,), "shared"),
    1: (2, 6, 6, 0, 0, 2, 0, (3,), "shared"),
    2: (3, 6, 5, 0, 0, 0, 0, (2,), "shared"),
    3: (2, 6, 7, 0, 1, 0, 0, (2,), "shared"),
    4: (1, 0, 5, 6, 0, 0, 2, (2, 3), "mode4"),
    5: (1, 0, 7, 8, 0, 0, 2, (2, 2), "mode5"),
    6: (1, 0, 7, 7, 1, 0, 0, (4,), "shared"),
    7: (2, 6, 5, 5, 1, 0, 0, (2,), "shared"),
}


def _weights(bits: int) -> list[int]:
    """The 64-scaled interpolation weights for an `n`-bit BC7 index."""
    top = (1 << bits) - 1
    return [(i * 64 + top // 2) // top for i in range(top + 1)]


WEIGHTS = {n: _weights(n) for n in (1, 2, 3, 4)}


def _expand(value: int, bits: int) -> int:
    """Expand an `bits`-wide endpoint component to 8 bits by bit replication."""
    if bits >= 8:
        return value & 0xFF
    return ((value << (8 - bits)) | (value >> max(0, 2 * bits - 8))) & 0xFF


def _rgb565(value: int) -> tuple[int, int, int]:
    return (_expand(value >> 11, 5), _expand((value >> 5) & 0x3F, 6),
            _expand(value & 0x1F, 5))


def _bc1_colors(block: bytes, four_colour: bool) -> tuple[list, list]:
    """The 4 colour entries and per-entry alpha for a BC1-style block."""
    c0 = block[0] | (block[1] << 8)
    c1 = block[2] | (block[3] << 8)
    e0, e1 = _rgb565(c0), _rgb565(c1)
    if c0 > c1 or four_colour:
        e2 = tuple((2 * e0[i] + e1[i]) // 3 for i in range(3))
        e3 = tuple((e0[i] + 2 * e1[i]) // 3 for i in range(3))
        colours = [e0, e1, e2, e3]
        alphas = [255, 255, 255, 255]
    else:
        e2 = tuple((e0[i] + e1[i]) // 2 for i in range(3))
        colours = [e0, e1, e2, (0, 0, 0)]
        alphas = [255, 255, 255, 0]
    return colours, alphas


def _bc1_block(block: bytes) -> list[tuple[int, int, int, int]]:
    colours, alphas = _bc1_colors(block, four_colour=False)
    indices = int.from_bytes(block[4:8], "little")
    out = []
    for i in range(16):
        c = (indices >> (2 * i)) & 3
        r, g, b = colours[c]
        out.append((r, g, b, alphas[c]))
    return out


def _bc2_block(block: bytes) -> list[tuple[int, int, int, int]]:
    colours, _ = _bc1_colors(block[8:16], four_colour=True)
    alpha = int.from_bytes(block[0:8], "little")
    out = []
    for i in range(16):
        nibble = (alpha >> (4 * i)) & 0xF
        r, g, b = colours[(int.from_bytes(block[12:16], "little") >> (2 * i)) & 3]
        out.append((r, g, b, nibble * 17))
    return out


def _bc3_alpha(block: bytes) -> list[int]:
    a0, a1 = block[0], block[1]
    values = [a0, a1]
    if a0 > a1:
        values += [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)]
    else:
        values += [((5 - k) * a0 + k * a1) // 5 for k in range(1, 5)]
        values += [0, 255]
    indices = int.from_bytes(block[2:8], "little")
    return [values[(indices >> (3 * i)) & 7] for i in range(16)]


def _bc3_block(block: bytes) -> list[tuple[int, int, int, int]]:
    alphas = _bc3_alpha(block)
    colours, _ = _bc1_colors(block[8:16], four_colour=True)
    indices = int.from_bytes(block[12:16], "little")
    out = []
    for i in range(16):
        r, g, b = colours[(indices >> (2 * i)) & 3]
        out.append((r, g, b, alphas[i]))
    return out


def _bc4_block(block: bytes) -> list[tuple[int, int, int, int]]:
    return [(v, 0, 0, 255) for v in _bc3_alpha(block)]


def _bc5_block(block: bytes) -> list[tuple[int, int, int, int]]:
    red = _bc3_alpha(block[0:8])
    green = _bc3_alpha(block[8:16])
    return [(red[i], green[i], 0, 255) for i in range(16)]


def _read_indices(read, width: int, anchors: tuple[int, ...]) -> list[int]:
    anchor_set = set(anchors)
    return [read(width - 1 if i in anchor_set else width) for i in range(16)]


def _subset_ids(nsub: int, partition: int) -> list[int]:
    if nsub == 1:
        return [0] * 16
    if nsub == 2:
        mask = BC7_PART2[partition]
        return [1 if (mask >> i) & 1 else 0 for i in range(16)]
    mask1, mask2 = BC7_PART3_1[partition], BC7_PART3_2[partition]
    ids = []
    for i in range(16):
        if (mask2 >> i) & 1:
            ids.append(2)
        elif (mask1 >> i) & 1:
            ids.append(1)
        else:
            ids.append(0)
    return ids


def _bc7_block(block: bytes) -> list[tuple[int, int, int, int]]:
    value = int.from_bytes(block[:16], "little")
    if value == 0:
        raise ValueError("BC7 block has no mode bit")
    mode = (value & -value).bit_length() - 1
    if mode > 7:
        raise ValueError(f"BC7 block mode {mode} is invalid")
    nsub, pb, rb, ab, epb, spb, rot_bits, widths, alpha_rule = BC7_MODES[mode]
    pos = mode + 1

    def read(width: int) -> int:
        nonlocal pos
        if width == 0:
            return 0
        out = (value >> pos) & ((1 << width) - 1)
        pos += width
        return out

    partition = read(pb)
    rotation = read(rot_bits)
    index_selection = read(1) if alpha_rule == "mode4" else 0

    channels = (rb, rb, rb, ab)
    endpoints = [[0] * (nsub * 2) for _ in range(4)]
    for channel, width in enumerate(channels):
        if width:
            for endpoint in range(nsub * 2):
                endpoints[channel][endpoint] = read(width)

    if epb:
        pbits = [read(1) for _ in range(nsub * 2)]
    elif spb:
        pbits = [read(1) for _ in range(nsub)]
    else:
        pbits = None

    expanded = [[0] * (nsub * 2) for _ in range(4)]
    for channel, width in enumerate(channels):
        if not width:
            continue
        for endpoint in range(nsub * 2):
            raw = endpoints[channel][endpoint]
            if epb:
                raw = (raw << 1) | pbits[endpoint]
                bits = width + 1
            elif spb:
                raw = (raw << 1) | pbits[endpoint // 2]
                bits = width + 1
            else:
                bits = width
            expanded[channel][endpoint] = _expand(raw, bits)

    anchors = {1: (0,), 2: BC7_ANCHOR2[partition], 3: BC7_ANCHOR3[partition]}[nsub]
    if alpha_rule == "shared":
        colour = _read_indices(read, widths[0], anchors)
        colour_weight = WEIGHTS[widths[0]]
        alpha_values = alpha_weight = None
    elif alpha_rule == "mode4":
        first = _read_indices(read, widths[0], anchors)
        second = _read_indices(read, widths[1], anchors)
        if index_selection:
            colour, colour_weight = second, WEIGHTS[widths[1]]
            alpha_values, alpha_weight = first, WEIGHTS[widths[0]]
        else:
            colour, colour_weight = first, WEIGHTS[widths[0]]
            alpha_values, alpha_weight = second, WEIGHTS[widths[1]]
    else:  # mode5
        colour = _read_indices(read, widths[0], anchors)
        colour_weight = WEIGHTS[widths[0]]
        alpha_values = _read_indices(read, widths[1], anchors)
        alpha_weight = WEIGHTS[widths[1]]

    subset_ids = _subset_ids(nsub, partition)

    out: list[tuple[int, int, int, int]] = []
    for i in range(16):
        subset = subset_ids[i]
        w = colour_weight[colour[i]]
        r = _mix(expanded[0][2 * subset], expanded[0][2 * subset + 1], w)
        g = _mix(expanded[1][2 * subset], expanded[1][2 * subset + 1], w)
        b = _mix(expanded[2][2 * subset], expanded[2][2 * subset + 1], w)
        if not ab:
            a = 255
        elif alpha_values is not None:
            a = _mix(expanded[3][2 * subset], expanded[3][2 * subset + 1],
                     alpha_weight[alpha_values[i]])
        else:
            a = _mix(expanded[3][2 * subset], expanded[3][2 * subset + 1], w)
        out.append((r, g, b, a))

    if rotation:
        swap = {1: 0, 2: 1, 3: 2}[rotation]
        rotated = []
        for pixel in out:
            pixel = list(pixel)
            pixel[3], pixel[swap] = pixel[swap], pixel[3]
            rotated.append(tuple(pixel))
        out = rotated
    return out


def _mix(e0: int, e1: int, weight: int) -> int:
    return (e0 * (64 - weight) + e1 * weight + 32) >> 6


BLOCK_DECODERS = {
    "BC1": _bc1_block, "BC2": _bc2_block, "BC3": _bc3_block,
    "BC4": _bc4_block, "BC5": _bc5_block, "BC7": _bc7_block,
}


class Image:
    """A decoded image: dimensions, format name and RGBA8 pixels."""

    __slots__ = ("width", "height", "format", "_pixels")

    def __init__(self, width: int, height: int, fmt: str,
                 pixels: list[tuple[int, int, int, int]]):
        self.width = width
        self.height = height
        self.format = fmt
        self._pixels = pixels

    def pixels(self) -> list[tuple[int, int, int, int]]:
        return self._pixels

    def rgba_bytes(self) -> bytes:
        return b"".join(bytes(px) for px in self._pixels)


def parse_header(data: bytes) -> tuple[int, int, str, int]:
    """Return (width, height, format, base_offset) or raise ValueError."""
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ValueError("not a DDS file (missing 'DDS ' magic)")
    (size, _flags, height, width, _pitch, _depth, _mips) = struct.unpack_from("<7I", data, 4)
    if size != 124:
        raise ValueError(f"bad DDS_HEADER size {size}, expected 124")
    if width == 0 or height == 0:
        raise ValueError(f"bad DDS dimensions {width}x{height}")
    pf_size, pf_flags, fourcc, bits = struct.unpack_from("<4I", data, 76)
    if pf_size != 32:
        raise ValueError(f"bad DDS pixel format size {pf_size}, expected 32")
    name = struct.pack("<I", fourcc)

    if name == b"DX10":
        if len(data) < 148:
            raise ValueError("DX10 DDS is truncated (missing extended header)")
        dxgi = struct.unpack_from("<I", data, 128)[0]
        fmt = PIXEL_FORMAT.get(dxgi)
        if fmt is None:
            raise ValueError(f"unsupported DXGI format {dxgi}")
        return width, height, fmt, 148

    if name in FOURCC_FORMAT:
        return width, height, FOURCC_FORMAT[name], 128

    if fourcc == 0 and (pf_flags & 0x40) and bits == 32:
        masks = struct.unpack_from("<4I", data, 92)
        if masks == (0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000):
            return width, height, "RGBA8", 128
        if masks == (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000):
            return width, height, "BGRA8", 128
        raise ValueError(f"unsupported 32-bit RGBA masks {masks}")

    if bits == 32 and fourcc == 0:
        raise ValueError("unsupported uncompressed DDS pixel format")
    shown = name.decode("latin-1") if all(32 <= c < 127 for c in name) else f"0x{fourcc:08x}"
    raise ValueError(f"unsupported DDS FourCC {shown!r}")


def decode(data: bytes) -> Image:
    """Decode the base level (mip 0) of a DDS file to RGBA8."""
    width, height, fmt, offset = parse_header(data)
    if fmt in UNCOMPRESSED:
        needed = width * height * 4
        payload = data[offset:offset + needed]
        if len(payload) < needed:
            raise ValueError(
                f"truncated {fmt} payload: {len(payload)} of {needed} bytes")
        pixels = []
        for i in range(0, needed, 4):
            r, g, b, a = payload[i:i + 4]
            pixels.append((r, g, b, a) if fmt == "RGBA8" else (b, g, r, a))
        return Image(width, height, fmt, pixels)

    block_bytes = BLOCK_BYTES[fmt]
    decoder = BLOCK_DECODERS[fmt]
    blocks_wide = (width + 3) // 4
    blocks_high = (height + 3) // 4
    needed = blocks_wide * blocks_high * block_bytes
    if len(data) - offset < needed:
        raise ValueError(
            f"truncated {fmt} payload: {len(data) - offset} of {needed} bytes")
    pixels = [(0, 0, 0, 255)] * (width * height)
    for by in range(blocks_high):
        for bx in range(blocks_wide):
            start = offset + (by * blocks_wide + bx) * block_bytes
            block = decoder(data[start:start + block_bytes])
            for yy in range(4):
                y = by * 4 + yy
                if y >= height:
                    break
                for xx in range(4):
                    x = bx * 4 + xx
                    if x < width:
                        pixels[y * width + x] = block[yy * 4 + xx]
    return Image(width, height, fmt, pixels)


def png_bytes(width: int, height: int,
              pixels: list[tuple[int, int, int, int]]) -> bytes:
    """Write an 8-bit RGBA PNG (IHDR/IDAT/IEND) with zlib and struct."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: none
        row = y * width
        for x in range(width):
            raw.extend(pixels[row + x])

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def _default_out(name: str) -> Path:
    return default_paths()["state"] / "tmp" / f"{name}.png"


def _write(data: bytes, out: str | None, name: str) -> int:
    image = decode(data)
    target = Path(out) if out else _default_out(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png_bytes(image.width, image.height, image.pixels()))
    print(json.dumps({
        "format": image.format, "width": image.width, "height": image.height,
        "out": str(target),
    }, indent=1))
    return 0


def cmd_decode(pak_rel: str, entry: str, out: str | None) -> int:
    import pakread
    data, _meta = pakread.read_entry(pak_rel, entry)
    return _write(data, out, Path(entry).stem)


def cmd_decode_file(path: str, out: str | None) -> int:
    return _write(Path(path).read_bytes(), out, Path(path).stem)


def selftest(db_path: Path | None = None) -> int:
    checks: list[tuple[str, bool]] = []
    try:
        rgba = bytes([10, 20, 30, 40] * 4)
        header = struct.pack("<7I", 124, 0x81007, 2, 2, 16, 0, 1) + b"\0" * 44
        pf = struct.pack("<8I", 32, 0x4, struct.unpack("<I", b"DX10")[0], 0, 0, 0, 0, 0)
        blob = (b"DDS " + header + pf + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
                + struct.pack("<5I", 28, 3, 0, 1, 0) + rgba)
        checks.append(("uncompressed RGBA8 decodes", decode(blob).pixels()[0] == (10, 20, 30, 40)))
    except Exception:  # noqa: BLE001
        checks.append(("uncompressed RGBA8 decodes", False))

    try:
        block = struct.pack("<HH", 0xF800, 0x07E0) + bytes([0xE4] * 4)
        header = struct.pack("<7I", 124, 0x81007, 4, 4, 8, 0, 1) + b"\0" * 44
        pf = struct.pack("<8I", 32, 0x4, struct.unpack("<I", b"DXT1")[0], 0, 0, 0, 0, 0)
        blob = b"DDS " + header + pf + struct.pack("<5I", 0x1000, 0, 0, 0, 0) + block
        checks.append(("BC1 decodes", decode(blob).pixels()[2] == (170, 85, 0, 255)))
    except Exception:  # noqa: BLE001
        checks.append(("BC1 decodes", False))

    try:
        block = bytes([255, 0, 0, 0, 0, 0, 0, 0]) + bytes(8)
        header = struct.pack("<7I", 124, 0x81007, 4, 4, 16, 0, 1) + b"\0" * 44
        pf = struct.pack("<8I", 32, 0x4, struct.unpack("<I", b"DXT5")[0], 0, 0, 0, 0, 0)
        blob = b"DDS " + header + pf + struct.pack("<5I", 0x1000, 0, 0, 0, 0) + block
        checks.append(("BC3 decodes", decode(blob).pixels()[0] == (0, 0, 0, 255)))
    except Exception:  # noqa: BLE001
        checks.append(("BC3 decodes", False))

    db = db_path or (default_paths()["state"] / "cache" / "pak-index" / "pakindex.db")
    if not db.exists():
        print(f"selftest: SKIP real decode - no index at {db}")
    else:
        row = None
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                row = con.execute(
                    "SELECT pak, path FROM entry "
                    "WHERE path LIKE 'lyshineui/%' AND path LIKE '%.dds' "
                    "ORDER BY usize ASC LIMIT 1").fetchone()
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            row = None
        if row is None:
            print(f"selftest: SKIP real decode - no lyshineui .dds in {db}")
        else:
            pak, entry = row
            try:
                import pakread
                data, _meta = pakread.read_entry(pak, entry)
                image = decode(data)
                png = png_bytes(image.width, image.height, image.pixels())
                ok = png.startswith(b"\x89PNG") and image.width > 0 and image.height > 0
                checks.append((f"real decode {pak}::{entry} -> {image.format} "
                               f"{image.width}x{image.height}", ok))
            except Exception as exc:  # noqa: BLE001
                print(f"  real decode failed: {exc}")
                checks.append((f"real decode {pak}::{entry}", False))

    ok = all(result for _, result in checks)
    for name, result in checks:
        print(f"{'PASS' if result else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    has_out = "--out" in argv
    out = argv[argv.index("--out") + 1] if has_out else None
    if cmd == "selftest":
        return selftest()
    try:
        if cmd == "decode" and len(argv) >= 3:
            return cmd_decode(argv[1], argv[2], out)
        if cmd == "decode-file" and len(argv) >= 2:
            return cmd_decode_file(argv[1], out)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
