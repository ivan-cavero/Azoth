"""Disassemble a VA window with Capstone (no Ghidra needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402


def main() -> int:
    p = default_paths()
    pe = PE(Path(p["exe"]))
    start = int(sys.argv[1], 16)
    length = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x120
    import capstone

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    code = pe.bytes_at(start, length) if hasattr(pe, "bytes_at") else None
    if code is None:
        # Any-section resolve: .text-only va_to_foff fails for .rdata/.data VAs.
        import struct

        data = pe.data
        pe_off = struct.unpack_from("<I", data, 0x3C)[0]
        nsec = struct.unpack_from("<H", data, pe_off + 6)[0]
        opt = struct.unpack_from("<H", data, pe_off + 20)[0]
        sec0 = pe_off + 24 + opt
        rva = start - 0x140000000
        foff = None
        for i in range(nsec):
            o = sec0 + i * 40
            vsize, vaddr, rsize, roff = struct.unpack_from("<IIII", data, o + 8)
            if vaddr <= rva < vaddr + max(vsize, rsize):
                foff = roff + rva - vaddr
                break
        if foff is None:
            raise SystemExit(f"VA {start:x} not mapped")
        code = data[foff : foff + length]
    for insn in md.disasm(code, start):
        print(f"{insn.address:x}  {insn.mnemonic} {insn.op_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
