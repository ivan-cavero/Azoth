"""Skip reasons for tests that need a live client, Windows, or the frida package.

WHY THIS EXISTS
===============
The atlas tool tests fall into two sets: those that run anywhere, and those that
read the installed client (a specific `NewWorld.exe`, its `typeindex.json`, and
frida to attach to it). MEASURED 2026-11-10: once CI finally reached this suite
it ran 285 tests and 8 failed for three unrelated reasons -

* `ctypes.windll` does not exist off Windows,
* the `frida` package is not installed on the runner,
* `private-client/` and its exe are not in the repo (they are the licensed,
  untracked client).

None of those is a defect in the code under test, and none of them can be fixed
on an Ubuntu runner. But a blanket skip would be worse than a failure: it would
also hide a real regression in a test that only happens to sit in the same file.
So each condition is named, narrow, and explains itself in the skip message -
the suite still fails if the CLIENT IS PRESENT and the tool misreads it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRIVATE = REPO / "private-client"
RUNTIME_EXE = PRIVATE / "runtime" / "Bin64" / "NewWorld.exe"
TYPEINDEX = PRIVATE / "runtime" / "typeindex.json"

NO_PRIVATE_CLIENT = (
    "the private client is not in this checkout (private-client/runtime/Bin64/"
    "NewWorld.exe is licensed and untracked); this test reads that client"
)
NOT_WINDOWS = "this test drives Windows APIs (ctypes.windll) and this is not Windows"
NO_FRIDA = "the frida package is not installed; this test attaches to a live process"


def has_private_client() -> bool:
    return RUNTIME_EXE.is_file()


def has_windows_api() -> bool:
    return sys.platform == "win32" and hasattr(__import__("ctypes"), "windll")


def has_frida() -> bool:
    return importlib.util.find_spec("frida") is not None
