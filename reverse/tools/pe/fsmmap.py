"""Dump the GameConnection FSM jump table (state -> case VA)."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    rip = 0x14644E7E8
    rcx = rip + 7 - 0x644E7EF
    b = rcx + 0x644EAB4
    d = rcx + 0x644EA94
    print("table base:", hex(rcx))
    fo = pe.va_to_foff(b)
    idx = pe.data[fo : fo + 0x33]
    fo2 = pe.va_to_foff(d)
    for i, bi in enumerate(idx):
        rel = struct.unpack_from("<i", pe.data, fo2 + bi * 4)[0]
        print(f"  state {i + 10}: -> {hex(rcx + rel)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
