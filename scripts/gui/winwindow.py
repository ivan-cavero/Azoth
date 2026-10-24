"""Shared window targeting for the private-run scripts.

WHY THIS EXISTS (measured 2026-10-10). Several scripts selected the game window by
a substring match on the title, e.g. `find_windows("New World")`. That also matches
any OTHER visible window containing that text -- in practice a browser tab titled
"Azoth - Servidor privado de New World". The consequences were real, not
hypothetical:

* `scripts/private-run.py` clicked "Play" on the wrong window and reported
  `FAIL: Play never started the login (character select not reached?)` while the
  client was sitting on character select the whole time.
* a Frida probe attached to the browser process instead of the game.

So: select the game by PROCESS IMAGE NAME, never by title. `game_windows()`
returns only windows owned by `NewWorld.exe`; the title is then used merely to
narrow within that process (the game title is "New World" or, when hung,
"New World (Not Responding)").

Usage:
    from winwindow import game_windows, find_game_window

    wins = game_windows()                 # [(hwnd, title)] of NewWorld.exe only
    hwnd = find_game_window()             # first one, or None
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GAME_EXE = "newworld.exe"

try:  # without this the process is DPI-virtualized and client rects lie
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except OSError:
    try:
        user32.SetProcessDPIAware()
    except OSError:
        pass


def _process_image_name(pid: int) -> str | None:
    """Basename of the executable behind `pid`, or None if it cannot be read."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _visible_windows() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(proc(cb), None)
    return out


def game_windows(title_sub: str = "new world") -> list[tuple[int, str]]:
    """Visible NewWorld.exe windows whose title contains `title_sub`.

    Empty when the game is not running -- that is the honest answer, and it is
    why callers should wait for it rather than fall back to a title match.
    """
    found: list[tuple[int, str]] = []
    for hwnd, title in _visible_windows():
        if title_sub and title_sub.lower() not in title.lower():
            continue
        if _process_image_name(_window_pid(hwnd)) == GAME_EXE:
            found.append((hwnd, title))
    return found


def find_game_window(title_sub: str = "new world") -> int | None:
    wins = game_windows(title_sub)
    return wins[0][0] if wins else None


def game_pids() -> list[int]:
    """Pids of the NewWorld.exe windows currently visible."""
    return sorted({_window_pid(hwnd) for hwnd, _ in game_windows()})


if __name__ == "__main__":
    wins = game_windows()
    print(f"NewWorld.exe windows: {len(wins)}")
    for hwnd, title in wins:
        print(f"  hwnd={hwnd:#x} pid={_window_pid(hwnd)} title={title!r}")
    others = [
        (hwnd, t)
        for hwnd, t in _visible_windows()
        if "new world" in t.lower() and _process_image_name(_window_pid(hwnd)) != GAME_EXE
    ]
    print(f"\nother windows containing 'new world' (correctly ignored): {len(others)}")
    for hwnd, t in others:
        print(f"  hwnd={hwnd:#x} exe={_process_image_name(_window_pid(hwnd))!r} title={t!r}")
