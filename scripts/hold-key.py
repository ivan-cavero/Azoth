"""Hold a key by SCAN CODE in a window (real SendInput), then release.

New World reads Raw Input; only SendInput with a real scan code reaches it, and
`orca computer press-key` cannot hold a key. Movement needs W held ~1.5 s.

Usage:
  python scripts/hold-key.py <title> <scan_hex> <seconds> [--click x,y]
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
SW_RESTORE = 9


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("padding", ctypes.c_ubyte * 24),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]


def find_window(title_sub: str) -> int:
    found: list[int] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)

    def cb(hwnd: int, _: object) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if title_sub.lower() in buf.value.lower():
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(proc(cb), None)
    if not found:
        raise SystemExit(f"no window matching {title_sub!r}")
    return found[0]


def send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def key_event(scan: int, up: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(type=INPUT_KEYBOARD, u=_UNION(ki=KEYBDINPUT(0, scan, flags, 0, None)))


def focus(hwnd: int) -> tuple[int, int]:
    # SetForegroundWindow alone is refused when our process is not the
    # foreground process, and then the synthesized key lands in whatever window
    # the user has (measured 2026-10-04: the game was in the world but the
    # foreground window was Discord, so every W test typed into Discord).
    # scripts/focus-window.py does the AttachThreadInput dance and verifies.
    import subprocess

    subprocess.run(
        [sys.executable, str(Path(__file__).with_name("focus-window.py")), "New World", "--check"],
        check=False,
        stdout=subprocess.DEVNULL,
    )
    if user32.GetForegroundWindow() != hwnd:
        raise SystemExit(
            "window did not take focus; refusing to send keys into another app"
        )
    time.sleep(0.2)
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def main() -> int:
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    title = sys.argv[1]
    scan = int(sys.argv[2], 16)
    seconds = float(sys.argv[3])
    click: tuple[int, int] | None = None
    if "--click" in sys.argv:
        raw = sys.argv[sys.argv.index("--click") + 1]
        cx, cy = raw.split(",")
        click = (int(cx), int(cy))

    hwnd = find_window(title)
    ox, oy = focus(hwnd)

    if click:
        user32.SetCursorPos(ox + click[0], oy + click[1])
        time.sleep(0.2)
        send(INPUT(type=INPUT_MOUSE, u=_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None))))
        time.sleep(0.08)
        send(INPUT(type=INPUT_MOUSE, u=_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None))))
        print(f"clicked client ({click[0]},{click[1]})")
        time.sleep(0.4)

    send(key_event(scan, False))
    time.sleep(seconds)
    send(key_event(scan, True))
    print(f"held scan 0x{scan:02X} for {seconds}s in hwnd=0x{hwnd:X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
