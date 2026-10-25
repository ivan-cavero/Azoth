#!/usr/bin/env python3
"""Screenshot the New World window -> PNG in the ignored project capture folder.

The model cannot read raw game PNGs directly: pair with shrink-image.py.
Usage: python ef.py shot [out.png]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path


def game_window_rect() -> tuple[int, int, int, int] | None:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "New World")
    if not hwnd:
        # Fallback: enumerate top-level windows for the exe title
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wt.HWND, wt.LPVOID
        )
        found = []

        @WNDENUMPROC
        def cb(h, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if "New World" in buf.value:
                found.append(h)
                return False
            return True

        user32.EnumWindows(cb, None)
        if not found:
            return None
        hwnd = found[0]
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else repo / ".azoth/captures/azoth_shot.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    rect = game_window_rect()
    if rect is None:
        print("New World window not found")
        return 1
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    l, t, r, b = rect
    w, h = r - l, b - t

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = ctypes.c_char * 0  # placeholder to keep flake quiet
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    hbmp = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(ctypes.c_void_p()), None, 0)
    gdi32.SelectObject(hdc_mem, hbmp)
    user32.PrintWindow(
        ctypes.windll.user32.FindWindowW(None, "New World") or 0,
        hdc_mem,
        2,  # PW_RENDERFULLCONTENT
    )
    # Read pixels back and write a BMP (stdlib-writable) via raw copy
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

    # BMP file: 14-byte file header + 40-byte info header + BGRA pixels
    import struct

    pixels = bytearray(buf.raw)
    # BGRA -> BGR rows, bottom-up (live check 2026-09-19: the DIB came
    # top-down into the buffer but the BMP writer assumed bottom-up, the
    # image showed vertically mirrored).
    row = bytearray()
    for y in range(h - 1, -1, -1):
        base = y * w * 4
        for x in range(w):
            o = base + x * 4
            row += pixels[o:o + 3]  # B,G,R
    row_size = w * 3
    pad = (4 - row_size % 4) % 4
    row_b = bytearray()
    for y in range(h):
        s = y * row_size
        row_b += row[s:s + row_size] + b"\x00" * pad
    data_size = 54 + len(row_b)
    bmp = struct.pack("<2sIHHIIiiHHIIiiII", b"BM", data_size, 0, 0, 54,
                      40, w, h, 1, 24, 0, len(row_b), 0, 0, 0, 0)
    out.write_bytes(bmp + bytes(row_b))
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
