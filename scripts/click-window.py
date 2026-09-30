"""Click a window at window-local coordinates using real input synthesis.

orca's click does not reach the game window, so this drives it with SendInput:
window-local (x, y) -> screen coords, focus, then a real left click.

Usage: python scripts/click-window.py <title-substring> <x> <y> [clicks]
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32


def set_dpi_aware() -> None:
    """Without this the process is DPI-virtualized: GetClientRect reports
    1022x569 for a 1280x720 window and every synthesized click lands offset."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except OSError:
        with contextlib.suppress(OSError):
            user32.SetProcessDPIAware()


set_dpi_aware()


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
SW_RESTORE = 9


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


def _origin(hwnd: int) -> tuple[int, int]:
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def click(title_sub: str, x: int, y: int, clicks: int = 1) -> str:
    wins = find_windows(title_sub)
    if not wins:
        raise SystemExit(f"no window matching {title_sub!r}")
    hwnd, name = wins[0]
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)  # let the OS finish focusing before the synthetic click
    ox, oy = _origin(hwnd)
    for _ in range(clicks):
        user32.SetCursorPos(ox + x, oy + y)
        time.sleep(0.15)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.08)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.4)
    return f"{name!r} clicked ({x},{y}) -> screen ({ox + x},{oy + y}) x{clicks}"


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("usage: click-window.py <title> <x> <y> [clicks]")
    try:
        x, y = int(sys.argv[2]), int(sys.argv[3])
        clicks = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    except ValueError as exc:
        raise SystemExit(f"x/y/clicks must be integers: {exc}") from exc
    print(click(sys.argv[1], x, y, clicks))


if __name__ == "__main__":
    main()
