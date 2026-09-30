#!/usr/bin/env python3
"""Intentionally refuses live process memory.

EAC EOS treats PROCESS_VM_READ like WRITE. A dump belongs after official
servers / EAC are gone, with no stealth.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_paths  # noqa: E402

BANNER = """
Refusing live NewWorld.exe memory.

EAC EOS ObRegisterCallbacks strips PROCESS_VM_READ and PROCESS_VM_WRITE.
Epic docs: an external dumper with memory rights kills the game.

Use instead:
  1. Game.log   tools/capture/nw_capture.py ingest|watch
  2. NIC        Start-NwCapture.bat  then  tools/reversing/net.py analyze
  3. Endpoints  tools/reversing/endpoints.py --session sessions/<session>
  4. EXE disk   tools/reversing/strings.py

After Jan 2027 / our REP without EAC: explicit ReadProcessMemory, no stealth.

docs/EAC.md
"""


def main() -> int:
  print(BANNER.strip())
  p = default_paths()
  exe = p["exe"]
  print(f"\nexe on disk: {exe} exists={exe.exists()}")
  return 2


if __name__ == "__main__":
  raise SystemExit(main())
