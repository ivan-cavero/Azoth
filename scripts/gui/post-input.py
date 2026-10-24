#!/usr/bin/env python3
"""Drive the game WITHOUT stealing the user's mouse or focus.

`send-input.py` / `click-window.py` synthesize REAL input: the cursor jumps,
the user's typing lands in the game. Unusable while the user is working.

This posts window messages (WM_KEYDOWN / WM_CHAR / WM_LBUTTONDOWN) straight
to the New World window queue: the real cursor never moves, focus never
changes, the window does not even come to the foreground.

Caveat: some engines read Raw Input instead of window messages; if the game
ignores these, fall back to send-input.py (accepting the focus steal) and
record it in LESSONS.md.

Usage (window-local client coordinates):
  python scripts/post-input.py key <VK_HEX>          # e.g. 1B = Escape
  python scripts/post-input.py text "<text>"
  python scripts/post-input.py click <x> <y>
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        with contextlib.suppress(OSError):
            user32.SetProcessDPIAware()


set_dpi_aware()


def find_window(title_sub: str) -> tuple[int, str]:
    out: list[tuple[int, str]] = []

    def cb(hwnd: int, _: object) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if title_sub.lower() in buf.value.lower():
            out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)(cb), 0
    )
    if not out:
        raise SystemExit(f"no window matching {title_sub!r}")
    return out[0]


def post_key(hwnd: int, vk: int) -> None:
    scan = user32.MapVirtualKeyW(vk, 0)
    lparam_down = (scan << 16) | 1
    lparam_up = (scan << 16) | 1 | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam_down)
    time.sleep(0.03)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam_up)
    time.sleep(0.05)


def post_char(hwnd: int, ch: str) -> None:
    code = ord(ch)
    user32.PostMessageW(hwnd, WM_CHAR, code, 1)
    time.sleep(0.02)


def post_click(hwnd: int, x: int, y: int) -> None:
    lparam = (y << 16) | (x & 0xFFFF)
    # WM_MOUSEMOVE first: UI layers track the cursor and ignore clicks at
    # coordinates the cursor never visited (live check 2026-09-19).
    for _ in range(3):
        user32.PostMessageW(hwnd, 0x0200, 0, lparam)
        time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    time.sleep(0.05)


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: post-input.py <title> key <VK_HEX> | text <text> | click <x> <y>"
        )
    title, mode = sys.argv[1], sys.argv[2]
    hwnd, name = find_window(title)
    if mode == "key":
        if len(sys.argv) < 4:
            raise SystemExit("key mode needs a VK in hex, e.g. 1B")
        vk = int(sys.argv[3], 16)
        post_key(hwnd, vk)
        print(f"{name!r} posted WM_KEYDOWN/UP VK 0x{vk:02X} (no focus stolen)")
    elif mode == "text":
        if len(sys.argv) < 4:
            raise SystemExit("text mode needs a string")
        for ch in sys.argv[3]:
            post_char(hwnd, ch)
        print(f"{name!r} posted {len(sys.argv[3])} WM_CHAR (no focus stolen)")
    elif mode == "click":
        if len(sys.argv) < 5:
            raise SystemExit("click mode needs x y")
        x, y = int(sys.argv[3]), int(sys.argv[4])
        post_click(hwnd, x, y)
        print(f"{name!r} posted WM_LBUTTONDOWN/UP ({x},{y}) (no focus stolen)")
    else:
        raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    main()
