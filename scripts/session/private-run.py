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

Two clients at once: `--instance 2` drives the SECOND private client against the
same world server (the launcher gives it its own pid/state files). The runbook
section "Two clients at once" has the literal commands and the list of what
still collides — the important one is that BOTH clients write ONE Game.log, so a
second client's session is verified in `.azoth/logs/world.log` (per `peer`) as
well as here.

Usage:
  python scripts/private-run.py                 # full run, client instance 1
  python scripts/private-run.py --instance 2    # the second client
  python scripts/private-run.py --no-launch     # attach to an already-running client
  python scripts/private-run.py --no-play       # stop at character select
  python scripts/private-run.py --pid 12345     # drive one exact client process
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "services" / "launcher" / "src" / "Start-NwPrivate.ps1"
PATCH_DIR = REPO / "services" / "launcher" / "runtime-tools"
PYTHON = REPO / ".azoth" / "venv" / "Scripts" / "python.exe"
PRIVATE = REPO / "private-client"

GAME_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "AGS" / "New World" / "Game.log"

# The client starts a fresh log on every launch by writing this line, i.e. it
# TRUNCATES Game.log instead of appending (verified against two consecutive
# sessions in %LOCALAPPDATA%\AGS\New World: each file begins with its own banner).
LOG_SESSION_BANNER = "Log Started at local time"

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

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def hwnd_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def find_window(title_sub: str = "New World", *, pid: int | None = None) -> list[tuple[int, str]]:
    """Windows of NewWorld.exe only -- never a window that merely says "New World".

    Delegate to scripts/winwindow.py, which filters by process image name. A
    substring match on the title also matches a browser tab (measured), which made
    this script click the wrong window and then report a false
    "character select not reached". The title filter is applied INSIDE the game
    process only.

    `pid` narrows to ONE client process. With two private clients open, "the
    first NewWorld.exe window" is whichever one Windows enumerates first, so a
    run that does not say which client it drives can drive the wrong one.
    """
    wins = game_windows(title_sub)
    if not wins:
        # The client appends "(Not Responding)" when it hangs; a caller's title
        # filter would then exclude the only window that matters.
        wins = game_windows("")
    if pid is not None:
        wins = [w for w in wins if hwnd_pid(w[0]) == pid]
    return wins


def client_size(hwnd: int) -> tuple[int, int]:
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def log_text() -> str:
    try:
        return GAME_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def session_text() -> str:
    """Game.log from the CURRENT client session onward, without the other client.

    Two measured facts force this instead of a byte offset taken before launch:

    * the client truncates Game.log on every launch, so an offset from before the
      launch does not describe the new session;
    * TWO clients share ONE Game.log path. The client resolves it through the
      Windows known-folder API and ignores the launcher's LOCALAPPDATA override
      (measured 2026-10-07), so the second client truncates the file the first
      client is still writing into.

    Anchoring on the last banner gives this client's own session start. The NUL
    cut matters only in the two-client case: the first client keeps writing at
    its old offset, so its later lines land after a run of NULs. Dropping them
    stops a healthy first client from making a broken second client look
    healthy. With no NULs (one client) nothing is cut.
    """
    text = log_text()
    mark = text.rfind(LOG_SESSION_BANNER)
    if mark < 0:
        return ""
    text = text[mark:]
    nul = text.find("\x00")
    return text if nul < 0 else text[:nul]


def wait_for_log(marker: str, *, timeout: float = 300.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker in session_text():
            return True
        time.sleep(2)
    return False


def state_dir(instance: int) -> Path:
    """Where the launcher writes this client's pid/source record.

    Instance 1 keeps the historical `private-client/state` (ef.py reads
    `state/game.pid` there); instance N>1 gets `state/instance-N`.
    """
    base = PRIVATE / "state"
    return base if instance == 1 else base / f"instance-{instance}"


def launcher_shell() -> str:
    """The PowerShell that can run `Start-NwPrivate.ps1`.

    MEASURED 2026-10-14: Windows PowerShell 5.1 on this machine loads
    `Microsoft.PowerShell.Utility` but does NOT expose `Get-FileHash`, which the launcher calls to
    record the client's source hash. The launcher then died with
    `The term 'Get-FileHash' is not recognized` and the game window never appeared, which
    `private-run.py` reports as `FAIL: window never appeared` - a launcher failure that looks like
    a client failure. PowerShell 7 (`pwsh`) is present and the runbook already records that it,
    not 5.1, is the shell that binds everything this script needs.
    """
    return shutil.which("pwsh") or "powershell.exe"


def launch(instance: int) -> None:
    """Start the launcher detached: it stays alive for the game's lifetime
    (`$p.WaitForExit()`), so a blocking run() would hang this script."""
    # One launcher log per instance: two clients appending to one file would
    # interleave their banner/pid lines. Instance 1 keeps the historical name.
    name = "private-run-launcher.log" if instance == 1 else f"private-run-launcher-instance{instance}.log"
    log = REPO / ".azoth" / "logs" / name
    log.parent.mkdir(parents=True, exist_ok=True)
    out = log.open("ab")
    subprocess.Popen(
        [
            launcher_shell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(LAUNCHER), "-Instance", str(instance),
        ],
        cwd=REPO,
        stdout=out,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def snapshot_shared_log(instance: int) -> None:
    """Keep the running client's log before a second client truncates it.

    The client ignores the launcher's LOCALAPPDATA override, so instance 2 and
    instance 1 share `%LOCALAPPDATA%\\AGS\\New World\\Game.log` and every launch
    truncates it. This copy is best-effort: if the client holds the file without
    read sharing, the copy fails and the run continues (the authoritative record
    of a two-client run is the world server log, which is per peer).
    """
    if not GAME_LOG.is_file():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = REPO / ".azoth" / "logs" / f"game-before-instance{instance}-{stamp}.log"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(GAME_LOG, dest)
    except OSError as exc:
        print(f"  [run] could not snapshot the shared Game.log: {exc}")
        return
    print(f"  [run] shared Game.log snapshotted to {dest.relative_to(REPO)}")


def wait_for_pid(instance: int, *, timeout: float = 180.0) -> int | None:
    """The pid the launcher recorded for this instance (`<state>/game.pid`)."""
    pid_file = state_dir(instance) / "game.pid"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            pid = int(pid_file.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            pid = 0
        if pid and find_window(pid=pid):
            return pid
        time.sleep(1)
    return None


def apply_patches() -> None:
    for name in PATCHES:
        script = PATCH_DIR / name
        if not script.is_file():
            print(f"  [run] missing patch {name}")
            continue
        print(f"  [run] {name}")
        subprocess.run([str(PYTHON), str(script)], cwd=REPO, check=False)


def patch_scripts_target() -> tuple[int, str] | None:
    """The window the world-phase patch scripts will write into.

    WHY this exists: patch-predicate-flag.py, patch-timeout-watchdog.py and
    patch-exit-to-menu.py resolve their target with
    `scripts/send-input.py::find_windows("New World")[0]`, which is a TITLE match
    over every visible window (no process filter) and takes the topmost. With two
    private clients open, the topmost "New World" window is not necessarily the
    client this run drives -- and those scripts write into process memory. Reuse
    their exact selection so this check cannot drift from what they will do.
    """
    helper = REPO / "scripts" / "send-input.py"
    spec = importlib.util.spec_from_file_location("azoth_send_input", helper)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    wins = module.find_windows("New World")
    return wins[0] if wins else None


def focus_hwnd(hwnd: int, attempts: int = 12) -> bool:
    """Bring ONE window to the foreground and prove it got there.

    `SetForegroundWindow` is refused when the calling process is not foreground,
    and a synthesized key then lands in whatever window the user has (measured
    2026-10-04: the game was in the world but the foreground window was Discord).
    The documented workaround is attaching to the foreground thread's input queue
    first (see scripts/focus-window.py). This variant takes an HWND instead of a
    title so it can pick between two identical "New World" windows.
    """
    for _ in range(attempts):
        if user32.GetForegroundWindow() == hwnd:
            return True
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        mine = kernel32.GetCurrentThreadId()
        attached: list[int] = []
        for tid in (foreground_thread, target_thread):
            if tid and tid != mine and user32.AttachThreadInput(mine, tid, True):
                attached.append(tid)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(mine, tid, False)
        time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD), ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _send_inputs(*inputs: "_INPUT") -> None:
    array = (_INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))


def hold_scan(hwnd: int, scan: int, seconds: float) -> bool:
    """Hold a key by SCAN CODE in one exact window (real SendInput).

    New World reads Raw Input, so only SendInput with a real scan code reaches it
    (a virtual key did not pass the title gate; measured). scripts/hold-key.py
    does the same thing but selects the window by title, which is ambiguous with
    two clients.
    """
    if not focus_hwnd(hwnd):
        return False
    down = _INPUT(type=1, u=_INPUTUNION(ki=_KEYBDINPUT(0, scan, 0x0008, 0, None)))
    up = _INPUT(type=1, u=_INPUTUNION(ki=_KEYBDINPUT(0, scan, 0x0008 | 0x0002, 0, None)))
    _send_inputs(down)
    time.sleep(seconds)
    _send_inputs(up)
    return True


def click_at(hwnd: int, x: int, y: int) -> bool:
    """Click a window-local point in one exact window (real SendInput)."""
    if not focus_hwnd(hwnd):
        return False
    origin = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    user32.SetCursorPos(origin.x + x, origin.y + y)
    time.sleep(0.2)
    _send_inputs(_INPUT(type=0, u=_INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, 0x0002, 0, None))))
    time.sleep(0.08)
    _send_inputs(_INPUT(type=0, u=_INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, 0x0004, 0, None))))
    time.sleep(0.4)
    return True


def click_play(hwnd: int, *, targeted: bool) -> str:
    """Click Play. `targeted` = drive this exact HWND instead of "the first window".

    The subprocess helpers (scripts/click-window.py) still select the first
    NewWorld.exe window, which is correct for a single client and ambiguous with
    two, so the default path is left exactly as it was verified.
    """
    w, h = client_size(hwnd)
    x, y = int(PLAY_X_FRAC * w), int(PLAY_Y_FRAC * h)
    if targeted:
        ok = click_at(hwnd, x, y)
        return f"clicked ({x},{y}) in hwnd={hwnd:#x} ok={ok}"
    result = subprocess.run(
        [
            str(PYTHON),
            str(REPO / "scripts" / "click-window.py"),
            "New World",
            str(x),
            str(y),
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


def slice_count() -> int:
    return session_text().count(SLICE_MARKER)


def verdict(*, waited_for_render_s: float = 0.0) -> str:
    text = session_text()
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
    global GAME_LOG

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instance", type=int, default=1,
                    help="which private client (1 = the historical one; 2+ = an "
                         "additional concurrent client)")
    ap.add_argument("--pid", type=int, default=None,
                    help="drive this exact NewWorld.exe process (implies --no-launch)")
    ap.add_argument("--log", default=None,
                    help="Game.log to read (default %%LOCALAPPDATA%%\\AGS\\New World\\Game.log)")
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

    if args.instance < 1:
        print("[run] --instance must be 1 or greater")
        return 2
    if args.log:
        GAME_LOG = Path(args.log)
    if args.pid:
        args.no_launch = True
    # Targeted mode: we know which process to drive, so every input and the
    # pre-patch check use that HWND instead of "the first New World window".
    targeted = args.pid is not None or args.instance > 1

    if args.instance > 1:
        print(f"[run] client instance {args.instance}")
        print("[run] NOTE: Game.log is shared with instance 1; verify this client in "
              ".azoth/logs/world.log (per-peer 'peer' field) too")

    if not args.no_launch:
        if args.instance > 1:
            snapshot_shared_log(args.instance)
        print("[run] launching the private client")
        launch(args.instance)
        time.sleep(8)

    pid = args.pid
    if targeted and pid is None:
        print(f"[run] waiting for the launcher to record instance {args.instance}'s pid")
        pid = wait_for_pid(args.instance)
        if pid is None:
            print(f"[run] FAIL: no pid in {state_dir(args.instance) / 'game.pid'}")
            return 1
        print(f"[run] instance {args.instance} pid={pid}")

    print("[run] waiting for the New World window")
    hwnd = None
    for _ in range(90):
        wins = find_window(pid=pid)
        if wins:
            hwnd = wins[0][0]
            break
        time.sleep(2)
    if hwnd is None:
        print("[run] FAIL: window never appeared")
        return 1
    print(f"[run] window {hwnd:#x} (pid {hwnd_pid(hwnd)}), client {client_size(hwnd)}")

    if not args.skip_splash:
        time.sleep(20)
        print("[run] passing the splash gate (Space)")
        if targeted:
            if not hold_scan(hwnd, 0x39, 0.15):
                print("[run] FAIL: the client window refused focus; refusing to send keys blind")
                return 1
            print(f"  held scan 0x39 for 0.15s in hwnd={hwnd:#x}")
        else:
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

    print("[run] applying world-phase patches at character select")
    if targeted:
        # These scripts patch memory and pick their own target window; refuse to
        # let them write into a different client.
        focus_hwnd(hwnd)
        time.sleep(0.5)
        chosen = patch_scripts_target()
        if chosen is None:
            print("[run] FAIL: no 'New World' window for the patch scripts")
            return 1
        if chosen[0] != hwnd:
            print(
                f"[run] FAIL: the patch scripts would target hwnd={chosen[0]:#x} "
                f"(pid {hwnd_pid(chosen[0])}), not this client's hwnd={hwnd:#x} "
                f"(pid {hwnd_pid(hwnd)}). Bring the instance {args.instance} window to the "
                "front and re-run; patching the wrong client is worse than not patching."
            )
            return 1
    apply_patches()

    if args.no_play:
        print("[run] --no-play: stopping at character select")
        return 0

    print("[run] clicking Play (retrying until the login queues)")
    for attempt in range(1, args.play_attempts + 1):
        print("  " + click_play(hwnd, targeted=targeted))
        for _ in range(6):
            time.sleep(5)
            if "Queuing login" in session_text() or "login ticket" in session_text():
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
        text = session_text()
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
            if slice_count() > 0:
                break
            time.sleep(5)
            waited = time.time() - spawn_at

    v = verdict(waited_for_render_s=waited)
    print(f"[run] verdict: {v}")
    if args.instance > 1:
        print("[run] this client's Game.log evidence is shared with instance 1; confirm the "
              "server saw two peers: grep '\"dtls-established\"' .azoth/logs/world.log")
    if v.startswith("InGame (state machine) but the world NEVER STARTED STREAMING"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
