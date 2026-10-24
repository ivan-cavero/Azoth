"""Find full string VAs the min-len filter of strings.py skips."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

NEEDLES = [
    b"REP socket connection established",
    b"is timeout : frames",
    b"connection_rep_registration_timeout",
]


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    for needle in NEEDLES:
        i = pe.data.find(needle)
        while i != -1:
            j = i
            while j < len(pe.data) and pe.data[j] != 0:
                j += 1
            s = pe.data[i:j].decode("ascii", "replace")
            va = pe.foff_to_va(i)
            print(hex(va) if va else f"no-va(fileoff {hex(i)})", repr(s[:100]))
            i = pe.data.find(needle, i + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
