"""Force a window to the foreground reliably, then optionally send input.

`SetForegroundWindow` is refused when the calling process is not the foreground
process, so a synthetic key press can silently land in whatever window the user
is using (measured 2026-10-04: the game was in the world but the foreground
window was Discord, and every "W does not move" measurement was sending the key
to Discord). The documented workaround is to attach to the foreground thread's
input queue first.

Usage:
  python scripts/focus-window.py "<title substring>" [--check]
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except OSError:
    user32.SetProcessDPIAware()

SW_RESTORE = 9


def find_window(title_sub: str) -> tuple[int, str]:
    found: list[tuple[int, str]] = []
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
            found.append((hwnd, buf.value))
            return False
        return True

    user32.EnumWindows(proc(cb), None)
    if not found:
        raise SystemExit(f"no visible window matching {title_sub!r}")
    return found[0]


def foreground_title() -> tuple[int, str]:
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return hwnd, buf.value


def focus(title_sub: str, attempts: int = 12) -> int:
    """Bring the window forward and keep trying until it really is foreground."""
    hwnd, name = find_window(title_sub)
    for _ in range(attempts):
        if user32.GetForegroundWindow() == hwnd:
            return hwnd
        user32.ShowWindow(hwnd, SW_RESTORE)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = kernel32.GetCurrentThreadId()
        attached: list[int] = []
        for tid in (fg_thread, target_thread):
            if tid and tid != me and user32.AttachThreadInput(me, tid, True):
                attached.append(tid)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(me, tid, False)
        time.sleep(0.15)
    return hwnd


def ensure_foreground(title_sub: str) -> int:
    hwnd = focus(title_sub)
    got, got_title = foreground_title()
    if got != hwnd:
        safe = got_title.encode("ascii", "replace").decode()
        raise SystemExit(
            f"focus refused: wanted 0x{hwnd:X} ({title_sub!r}), foreground is "
            f"0x{got:X} ({safe!r})"
        )
    return hwnd


def main() -> int:
    title = sys.argv[1] if len(sys.argv) > 1 else "New World"
    hwnd = focus(title)
    got, got_title = foreground_title()
    safe = got_title.encode("ascii", "replace").decode()
    ok = got == hwnd
    print(f"target 0x{hwnd:X} ({title!r}) foreground=0x{got:X} ({safe!r}) ok={ok}")
    if "--check" in sys.argv and not ok:
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
