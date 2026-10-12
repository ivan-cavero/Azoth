"""One-shot: restore the two `b"\\x00\\x01"` literals that a shell heredoc mangled.

A heredoc turned the escape sequences into real NUL/SOH bytes, so the test module
stopped importing ("source code string cannot contain null bytes"). This script
builds both patterns from explicit byte values so no shell escaping is involved.
"""

from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "services" / "world" / "tests" / "test_rep.py"
BS = bytes([92])                     # a single backslash
BAD = b'b"' + bytes([0, 1]) + b'"'   # what is in the file now
GOOD = b'b"' + BS + b"x00" + BS + b"x01" + b'"'

raw = PATH.read_bytes()
print("bad occurrences:", raw.count(BAD))
raw = raw.replace(BAD, GOOD)
PATH.write_bytes(raw)
print("nul bytes left:", raw.count(bytes([0])))
