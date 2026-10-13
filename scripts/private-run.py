#!/usr/bin/env python3
"""Drive one private-client run end to end without a human at the keyboard.

Why this exists: every world attempt needs the same manual dance (pass the
splash gate, wait for character select, apply the world-phase memory patches,
click Play). Doing it by hand makes overnight A/B work impossible and leaves
the patch timing to chance — and applying the world-phase patches during load
hangs the client (see research/docs/PRIVATE-CLIENT-RUNBOOK.md).

Sequence:
  1. launch the private client (Start-NwPrivate.ps1, no -Watch)
  2. wait for the window, then pass the splash gate with a scan-code Space
  3. wait for `OnCampfireLoginComplete` in Game.log, then settle
  4. apply the world-phase patches (predicate flag, watchdog, spawn gate)
  5. click Play
  6. watch Game.log for InGame / a failure boundary, print a verdict

Usage:
  python scripts/private-run.py                 # full run
  python scripts/private-run.py --no-launch     # attach to an already-running client
  python scripts/private-run.py --no-play       # stop at character select
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "services" / "launcher" / "src" / "Start-NwPrivate.ps1"
PATCH_DIR = REPO / "services" / "launcher" / "runtime-tools"
PYTHON = REPO / ".azoth" / "venv" / "Scripts" / "python.exe"

GAME_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "AGS" / "New World" / "Game.log"

# World-phase patches. Fixed-byte patches are stdlib memory writes, never Frida.
PATCHES = (
    "patch-predicate-flag.py",    # ClientContext::Initialize gets the ok flag
    "patch-timeout-watchdog.py",  # never force the InGame disconnect
    "patch-spawn-gate.py",        # NOP the spawn gate's null check
    # The 20-minute "exit to main menu" delegate. NOPing 0x141004230 was NOT
    # enough (measured 2026-10-11): that is only the ActorContainerDisconnect
    # notification, and the same delegate continues to the real exit at
    # 0x14100425F. This patch targets that call. See
    # .azoth/night/subagent-20min-exit-real-path.md.
    "patch-exit-to-menu.py",
)

# Play button as a fraction of the client rect (measured 2026-10-07, 1366x768).
# The fractions are resolution-independent, but they are only correct if the rect
# belongs to the GAME window: until 2026-10-10 the lookup matched a browser tab
# titled "Azoth - Servidor privado de New World", so every click went elsewhere.
PLAY_X_FRAC = 1185 / 1366
PLAY_Y_FRAC = 662 / 768


sys.path.insert(0, str(Path(__file__).resolve().parent))
from winwindow import game_windows  # noqa: E402


def find_window(title_sub: str = "New World") -> list[tuple[int, str]]:
    """Windows of NewWorld.exe only -- never a window that merely says "New World".

    Delegate to scripts/winwindow.py, which filters by process image name. A
    substring match on the title also matches a browser tab (measured), which made
    this script click the wrong window and then report a false
    "character select not reached". The title filter is applied INSIDE the game
    process only.
    """
    wins = game_windows(title_sub)
    if wins:
        return wins
    # The client appends "(Not Responding)" when it hangs; a caller's title filter
    # would then exclude the only window that matters.
    return game_windows("")


def client_size(hwnd: int) -> tuple[int, int]:
    user32 = ctypes.windll.user32
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def log_text() -> str:
    try:
        return GAME_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def wait_for_log(marker: str, *, timeout: float = 300.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker in log_text():
            return True
        time.sleep(2)
    return False


def launch() -> None:
    """Start the launcher detached: it stays alive for the game's lifetime
    (`$p.WaitForExit()`), so a blocking run() would hang this script."""
    log = REPO / ".azoth" / "logs" / "private-run-launcher.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    out = log.open("ab")
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER)],
        cwd=REPO,
        stdout=out,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def apply_patches() -> None:
    for name in PATCHES:
        script = PATCH_DIR / name
        if not script.is_file():
            print(f"  [run] missing patch {name}")
            continue
        print(f"  [run] {name}")
        subprocess.run([str(PYTHON), str(script)], cwd=REPO, check=False)


def click_play(hwnd: int) -> str:
    w, h = client_size(hwnd)
    result = subprocess.run(
        [
            str(PYTHON),
            str(REPO / "scripts" / "click-window.py"),
            "New World",
            str(int(PLAY_X_FRAC * w)),
            str(int(PLAY_Y_FRAC * h)),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout or result.stderr).strip()


# The world actually STREAMING, measured as log lines the client only emits while it
# loads world slices. Measured 2026-10-13 by comparing two sessions on this build:
#
#   session that rendered the world : 40 post-spawn non-boilerplate lines, 26 `[WARNING] Slice:`
#   session stuck in a loading screen:  5 post-spawn non-boilerplate lines,  0 `[WARNING] Slice:`
#
# and the stuck one still reported `player spawn succeeds` + `Update state ... InGame`, so the
# state machine saying InGame does NOT mean the world rendered. A runner that only checks the
# state machine will call a hung loading screen a success, which it did until this was added.
SLICE_MARKER = "[WARNING] Slice:"


def slice_count(mark: int) -> int:
    return log_text()[mark:].count(SLICE_MARKER)


def verdict(mark: int, *, waited_for_render_s: float = 0.0) -> str:
    text = log_text()[mark:]
    if "player spawn succeeds, in game" in text:
        head = text.split("player spawn succeeds")[0]
        if "[ClientContext] Cleanup()" in head[-600:]:
            return "InGame reached but ClientContext was cleaned up (predicate flag missing?)"
        slices = text.count(SLICE_MARKER)
        if slices == 0:
            return (
                f"InGame (state machine) but the world NEVER STARTED STREAMING - 0 "
                f"'{SLICE_MARKER.rstrip()}' lines after {waited_for_render_s:.0f}s; the client is "
                "most likely hung on a loading screen. Do NOT treat this as a rendered world."
            )
        return f"InGame reached, world streaming ({slices} slice lines), player possessed"
    if "transport_security_error" in text:
        return "DTLS rejected (gate 4: run scripts/patch-dtls-disk.py apply)"
    if "connection_player_timeout" in text:
        return "connection_player_timeout (gate 6/7: check the world env)"
    if "registration response" not in text and "WaitingForREPConnection" in text:
        return "stuck before REP registration"
    return "no InGame marker yet"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-launch", action="store_true")
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--skip-splash", action="store_true", help="do not send Space")
    ap.add_argument("--settle", type=float, default=60.0,
                    help="seconds to wait after the splash key before patching/Play")
    ap.add_argument("--play-attempts", type=int, default=8)
    ap.add_argument("--login-timeout", type=float, default=420.0)
    ap.add_argument("--render-timeout", type=float, default=90,
                    help="seconds after spawn to wait for the client to start "
                         "streaming the world (Slice lines); 0 disables the wait")
    args = ap.parse_args()

    if not args.no_launch:
        print("[run] launching the private client")
        launch()
        time.sleep(8)

    print("[run] waiting for the New World window")
    hwnd = None
    for _ in range(90):
        wins = find_window()
        if wins:
            hwnd = wins[0][0]
            break
        time.sleep(2)
    if hwnd is None:
        print("[run] FAIL: window never appeared")
        return 1
    print(f"[run] window {hwnd:#x}, client {client_size(hwnd)}")

    if not args.skip_splash:
        time.sleep(20)
        print("[run] passing the splash gate (Space)")
        subprocess.run(
            [str(PYTHON), str(REPO / "scripts" / "hold-key.py"), "New World", "0x39", "0.15"],
            cwd=REPO,
            check=False,
        )

    # `OnCampfireLoginComplete` fires during the INITIAL load, before the splash
    # gate, so it is not a character-select marker. Wait a fixed settle window
    # instead, then let the Play click retry until the login actually queues.
    print(f"[run] settling {args.settle:.0f}s for the frontend and character select")
    time.sleep(args.settle)

    mark = len(log_text())
    print("[run] applying world-phase patches at character select")
    apply_patches()

    if args.no_play:
        print("[run] --no-play: stopping at character select")
        return 0

    print("[run] clicking Play (retrying until the login queues)")
    for attempt in range(1, args.play_attempts + 1):
        print("  " + click_play(hwnd))
        for _ in range(6):
            time.sleep(5)
            if "Queuing login" in log_text()[mark:] or "login ticket" in log_text()[mark:]:
                print(f"[run] login started on attempt {attempt}")
                break
        else:
            continue
        break
    else:
        print("[run] FAIL: Play never started the login (character select not reached?)")
        return 1

    print("[run] watching for the world")
    spawn_at = None
    deadline = time.time() + 180
    while time.time() < deadline:
        text = log_text()[mark:]
        if "player spawn succeeds, in game" in text:
            spawn_at = time.time()
            break
        if "OnConnectionFail" in text or "Connection fail" in text:
            break
        time.sleep(5)

    # After the spawn marker, give the client a bounded window to actually stream the world.
    # Without this the slice count is read too early and a working session looks stuck.
    waited = 0.0
    if spawn_at is not None:
        render_deadline = time.time() + args.render_timeout
        while time.time() < render_deadline:
            if slice_count(mark) > 0:
                break
            time.sleep(5)
            waited = time.time() - spawn_at

    v = verdict(mark, waited_for_render_s=waited)
    print(f"[run] verdict: {v}")
    if v.startswith("InGame (state machine) but the world NEVER STARTED STREAMING"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
