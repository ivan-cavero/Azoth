"""Dump every StackConfig key read alongside the game-security category."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402


def s_at(pe, va, cap=60):
    fo = pe.va_to_foff(va)
    if fo is None:
        return None
    end = pe.data.find(b"\x00", fo)
    s = pe.data[fo:end][:cap]
    if all(32 <= c < 127 or c == 0 for c in s) and len(s) > 3:
        return s.decode("ascii", "replace")
    return None


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    import struct as st

    text = pe.section(".text")
    data = pe.data
    sites = []
    for off in range(text["raw"], text["raw"] + text["rsize"] - 7):
        if data[off] in (0x48, 0x4C, 0x49, 0x4D) and data[off + 1] == 0x8D and (data[off + 2] & 0xC7) == 0x05:
            disp = st.unpack_from("<i", data, off + 3)[0]
            va = text["va"] + (off - text["raw"])
            if va + 7 + disp == 0x1484CB2F0:  # game-security
                sites.append(va)
    print(len(sites), "game-security sites")
    for site in sites:
        # the KEY is read ~0x100-0x200 bytes later via another lea; scan ahead
        fo = pe.va_to_foff(site)
        found = []
        for off in range(fo, fo + 0x300):
            if data[off] in (0x48, 0x4C, 0x49, 0x4D) and data[off + 1] == 0x8D and (data[off + 2] & 0xC7) == 0x05:
                disp = st.unpack_from("<i", data, off + 3)[0]
                va = text["va"] + (off - text["raw"])
                s = s_at(pe, va + 7 + disp)
                if s and "%" not in s and "." not in s and " " not in s and s != "game-security":
                    found.append(s)
        print(hex(site), "->", found[:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
