"""Send a key or type text into a window (real SendInput).

Used to drive the game's own console: orca's press-key does not support keys like
`~`, and keyboard input is the only channel that reaches the New World window.

**KEYS ARE SENT AS SCAN CODES, NOT VIRTUAL KEY CODES.** Measured 2026-10-19 and it cost a false
negative: this script used to send a VK with no `KEYEVENTF_SCANCODE`, so pressing TAB (VK 0x09) and
I (VK 0x17) did nothing, and that was misread as "the inventory UI does not open". The same session
proved input WAS arriving - holding W moved the player - so the correct reading was "this path does
not deliver that key". `scripts/hold-key.py` already documents the rule: New World reads Raw Input,
and only SendInput with a real scan code reaches it.

`key` now takes a SCAN code (the same number hold-key.py takes). A VK is still accepted via
`vk <VK_HEX>` for paths that want one, but it is not the default because it is not reliable here.

Usage:
  python scripts/send-input.py <title> key <SCAN_HEX>     # e.g. TAB 0x0F, W 0x11
  python scripts/send-input.py <title> vk <VK_HEX>
  python scripts/send-input.py <title> text "<text>"
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004
SW_RESTORE = 9


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_ubyte * 24)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


def find_windows(title_sub: str) -> list[tuple[int, str]]:
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
    return out


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key(vk: int) -> None:
    _send(INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(vk, 0, 0, 0, None))))
    time.sleep(0.03)
    _send(
        INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTunion(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)),
        )
    )
    time.sleep(0.05)


def _scan(code: int) -> None:
    """Press and release a key by SCAN CODE, which is what this client actually reads."""
    flags = KEYEVENTF_SCANCODE
    _send(INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(0, code, flags, 0, None))))
    time.sleep(0.03)
    _send(
        INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTunion(
                ki=KEYBDINPUT(0, code, flags | KEYEVENTF_KEYUP, 0, None)
            ),
        )
    )
    time.sleep(0.05)


def _char(ch: str) -> None:
    code = ord(ch)
    _send(
        INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)),
        )
    )
    time.sleep(0.02)
    _send(
        INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTunion(
                ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
            ),
        )
    )
    time.sleep(0.03)


def focus(title_sub: str) -> str:
    wins = find_windows(title_sub)
    if not wins:
        raise SystemExit(f"no window matching {title_sub!r}")
    hwnd, name = wins[0]
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    return name


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "usage: send-input.py <title> key <SCAN_HEX> | vk <VK_HEX> | text <text>"
        )
    title, mode = sys.argv[1], sys.argv[2]
    name = focus(title)
    if mode == "key":
        try:
            scan = int(sys.argv[3], 16)
        except ValueError as exc:
            raise SystemExit(f"scan code must be hex, e.g. 0F: {exc}") from exc
        _scan(scan)
        print(f"{name!r} sent scan 0x{scan:02X}")
    elif mode == "vk":
        try:
            vk = int(sys.argv[3], 16)
        except ValueError as exc:
            raise SystemExit(f"VK must be hex, e.g. C0: {exc}") from exc
        _key(vk)
        print(f"{name!r} sent VK 0x{vk:02X} (no scan code: may not reach Raw Input)")
    elif mode == "text":
        for ch in sys.argv[3]:
            _char(ch)
        print(f"{name!r} typed {len(sys.argv[3])} chars")
    else:
        raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    main()
