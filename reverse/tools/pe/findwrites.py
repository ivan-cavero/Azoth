"""Find code writing/adding to [reg+0xE0] near Carrier objects (heuristic)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from catalog import PE  # noqa: E402


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    text = pe.section(".text")
    data = pe.data
    raw, rsize = text["raw"], text["rsize"]
    hits = []
    for i in range(raw, raw + rsize - 6):
        b0, b1 = data[i], data[i + 1]
        # C7 4x disp8 imm32 (mov dword [reg+disp8], imm)
        if b0 == 0xC7 and 0x40 <= b1 <= 0x57 and data[i + 2] == 0xE0:
            va = text["va"] + (i - raw)
            imm = int.from_bytes(data[i + 3 : i + 7], "little")
            hits.append((va, f"mov dword [r*+0xE0], {imm}"))
        # C7 8x disp32
        elif b0 == 0xC7 and 0x80 <= b1 <= 0x97 and data[i + 2] == 0xE0:
            va = text["va"] + (i - raw)
            imm = int.from_bytes(data[i + 3 : i + 7], "little")
            hits.append((va, f"mov dword [r*+0xE0], {imm}"))
    for va, s in hits[:60]:
        print(hex(va), s)
    print(len(hits), "total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
