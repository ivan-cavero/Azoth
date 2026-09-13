"""Capture a window's client area at native resolution (PIL ImageGrab, no deps).

Usage: python scripts/capture-window.py <title-substring> <out.png>
"""

import contextlib
import ctypes
import sys
import time
from ctypes import wintypes

from PIL import ImageGrab


def set_dpi_aware() -> None:
    """Without this the process is DPI-virtualized: GetClientRect reports
    1022x569 for a 1280x720 window, so the capture and every click land offset."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except OSError:
        with contextlib.suppress(OSError):
            ctypes.windll.user32.SetProcessDPIAware()


set_dpi_aware()

WM_GETTEXT = 0x000D
SW_RESTORE = 9


def bring_to_front(hwnd: int) -> None:
    """ImageGrab reads the SCREEN rect, so an overlapping console would be
    captured instead of the game. Focus the target first."""
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)


def find_windows(title_sub: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []

    def cb(hwnd: int, _: object) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        if title_sub.lower() in buf.value.lower():
            out.append((hwnd, buf.value))
        return True

    ctypes.windll.user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)(cb), 0
    )
    return out


def client_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT()
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


def main() -> None:
    title_sub, out = sys.argv[1], sys.argv[2]
    wins = find_windows(title_sub)
    if not wins:
        print(f"no window matching {title_sub!r}", file=sys.stderr)
        sys.exit(2)
    hwnd, name = wins[0]
    bring_to_front(hwnd)
    bbox = client_rect(hwnd)
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    img.save(out)
    print(f"{name!r} bbox={bbox} -> {out}")


if __name__ == "__main__":
    main()
