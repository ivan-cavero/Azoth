"""Compatibility shim. The command is python ef.py."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

print("az.py now calls ef.py. Use: python ef.py", file=sys.stderr)
target = Path(__file__).with_name("ef.py")
sys.argv[0] = str(target)
runpy.run_path(str(target), run_name="__main__")
