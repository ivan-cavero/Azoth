"""Repo-local output paths and shared shutdown used by private-client probes.

THE SHUTDOWN MATTERS AS MUCH AS THE MEASUREMENT
===============================================
Measured 2026-10-12 (three crashes, one signature): a probe that hooks a hot
function and then simply calls ``session.detach()`` can kill the client after the
data is already collected. Windows reports it as

    Event Name: BEX64
    P4: frida-agent.dll_unloaded      <- note: ALREADY unloaded
    P7: 000000000009c7e0              <- RVA into frida-agent.dll
    P8: c0000005                      <- access violation
    P9: 0000000000000008              <- execute violation (DEP), not read/write

and ``0x9c7e0`` is the **first instruction** of a 1015-byte function
(``0x9c7e0..0x9cbd7`` in ``.pdata``), i.e. a thread branched to a function entry
inside a module that had already been unmapped. That is a plain execute-after-unload
race, and ``Game.log`` says nothing about it — no ``Cleanup()``, no
``exiting to main menu``, no ``Disconnected from REP`` — which is exactly why such a
death is easy to misread as client behaviour.

Two ways out, both better than a bare ``detach()``:

``kill=True`` (default for hot-hook probes)
    End the client deliberately with ``device.kill()``. No unload, no race, no crash
    report, no ambiguity. This is usually the RIGHT choice for this project: every
    world A/B already needs a fresh ``NewWorld.exe``, so the process is spent anyway.

``kill=False``
    A best-effort orderly teardown, in the order that gives the race the least room:
    ask the script to run ``Interceptor.detachAll()`` (so no thread can still be
    routed into agent code through a hook), settle, ``script.unload()`` (Frida's own
    teardown), settle, then ``session.detach()``. Use it only when the session must
    survive.

Probes that hook a hot function must export ``teardown``. A probe that does not
export it still works with ``kill=True``; with ``kill=False`` the helper warns.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_STATE = REPO_ROOT / ".azoth"


def project_log(name: str) -> Path:
    path = LOCAL_STATE / "logs" / Path(name).name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def probe_capture(name: str) -> Path:
    path = LOCAL_STATE / "captures" / "probes" / Path(name).name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def safe_shutdown(
    session,
    script=None,
    *,
    kill: bool,
    device=None,
    settle_s: float = 1.5,
    log=print,
) -> str:
    """End a probe's Frida session without the execute-after-unload race.

    Returns the strategy actually used, so the caller can record it in the capture:
    ``"kill"``, ``"teardown+unload+detach"`` or ``"detach"``.

    ``kill=True`` needs a device. Frida 17's ``Session`` has no ``.device`` attribute,
    so the caller must pass the device it attached through; without it this degrades to
    the detach path rather than failing.
    """
    import time

    if kill:
        if device is None:
            log("[shutdown] kill requested but no device was passed; using detach")
        else:
            try:
                pid = session.pid
            except Exception as exc:  # noqa: BLE001
                log(f"[shutdown] cannot read pid ({exc}); using detach")
            else:
                log(f"[shutdown] device.kill({pid}) - deliberate, no agent unload race")
                device.kill(pid)
                return "kill"

    strategy = []
    if script is not None:
        try:
            script.exports_sync.teardown()  # Interceptor.detachAll() in the agent
            strategy.append("teardown")
            time.sleep(settle_s)
        except Exception as exc:  # noqa: BLE001
            log(f"[shutdown] no/!failed teardown export ({exc}); "
                "hooks stay installed until unload")
        try:
            script.unload()
            strategy.append("unload")
            time.sleep(settle_s)
        except Exception as exc:  # noqa: BLE001
            log(f"[shutdown] script.unload failed: {exc}")
    try:
        session.detach()
        strategy.append("detach")
    except Exception as exc:  # noqa: BLE001
        log(f"[shutdown] detach failed: {exc}")
    return "+".join(strategy) or "none"
