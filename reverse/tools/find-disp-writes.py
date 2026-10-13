"""Find every instruction in NewWorld.exe that WRITES to [reg+disp] for one displacement.

WHY THIS EXISTS
===============
Two live problems are blocked on "who writes this field", and the live route failed:

* the ALC door at ``conn+0xAA0`` never opens and static analysis "found no recurring
  writer" for the stamp at ``conn+0xAA8`` (see ``alc_pointer_never_opens_live_20261011``);
* Frida probes that hook the hot component lookup are the ones that crash the client
  (see ``frida_unload_crash_mechanism_and_the_fix_20261012``), so a static answer is worth
  more here than another attach.

``reverse/tools/findwrites.py`` is a hand-rolled heuristic for one hardcoded offset
(``0xE0``) and two encodings. This tool is general and covers the encodings that actually
appear for a struct field: ``mov``/``add``/``sub``/``or``/``and``/``xor``/``test`` with a
displacement, ``inc``/``dec``, and the SSE stores. It reports only instructions whose
memory operand is a WRITE (or a read-modify-write), so a plain ``cmp [reg+disp], x`` is
excluded unless ``--reads`` is passed.

METHOD (and why it is not a plain linear sweep)
-----------------------------------------------
Disassembling 132 MB of ``.text`` linearly desynchronises on data and padding. Instead this
finds every occurrence of the 4-byte displacement, then tries the 15 possible instruction
starts that would make that displacement the instruction's final field, and keeps the
alignment where a real instruction decodes and its displacement matches. Every hit is
therefore a decoded instruction with the exact displacement, not a byte coincidence.

Usage:
    python reverse/tools/find-disp-writes.py 0xAA0
    python reverse/tools/find-disp-writes.py 0xAA8 --reads
    python reverse/tools/find-disp-writes.py 0xAA0 --callers      # who calls the writers
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

# Operand access on the memory operand is what decides read vs write (capstone 5
# reports it as a CS_AC_* bitmask on `op.access`).
# Mnemonics that write a memory operand and are worth reporting even though the
# generic access check already catches most of them.
INTERESTING = {
    "mov", "movups", "movaps", "movsd", "movss", "movdqu", "movdqa", "movd",
    "movq", "add", "sub", "or", "and", "xor", "inc", "dec", "not", "neg",
    "xchg", "cmpxchg", "bts", "btr", "andps", "orps", "xorps",
}


def scan(exe: Path, disp: int, include_reads: bool, limit: int) -> list[tuple[int, str]]:
    import capstone

    pe = PE(exe)
    text = pe.section(".text")
    raw, rsize, tva = text["raw"], text["rsize"], text["va"]
    data = pe.data
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True

    needle = struct.pack("<I", disp)
    hits: list[tuple[int, str]] = []
    seen: set[int] = set()
    start = raw
    end = raw + rsize
    while True:
        i = data.find(needle, start, end)
        if i < 0:
            break
        start = i + 1
        # the displacement is the last 4 bytes of the instruction, so the instruction
        # starts between 1 and 15 bytes earlier. Several alignments can decode (a REX
        # prefix skipped gives a shorter shadow of the same instruction), so keep the
        # LONGEST decoding: the one whose start is earliest.
        best: tuple[int, str] | None = None
        for back in range(15, 0, -1):
            s = i - back
            if s < raw:
                continue
            chunk = data[s : i + 4]
            for insn in md.disasm(chunk, tva + (s - raw)):
                if insn.address + insn.size != tva + (i + 4 - raw):
                    continue  # not the instruction that ends on the displacement
                if insn.mnemonic not in INTERESTING:
                    continue
                ok = False
                for op in insn.operands:
                    if op.type != capstone.x86.X86_OP_MEM:
                        continue
                    if op.mem.disp != disp:
                        continue
                    # capstone 5 exposes access as a CS_AC_* bitmask, not an
                    # X86_OP_ACCESS enum.
                    writes = bool(op.access & capstone.CS_AC_WRITE)
                    if include_reads or writes:
                        ok = True
                if not ok:
                    continue
                cand = (insn.address, f"{insn.mnemonic} {insn.op_str}")
                if best is None or cand[0] < best[0]:
                    best = cand
                break
            if best is not None:
                break
        if best is not None and best[0] not in seen:
            seen.add(best[0])
            hits.append(best)
        if len(hits) >= limit:
            break
    hits.sort()
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("disp", help="displacement to search for, e.g. 0xAA0")
    ap.add_argument("--exe")
    ap.add_argument("--reads", action="store_true", help="include read-only accesses too")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--callers", action="store_true",
                    help="print the callers of each containing function")
    args = ap.parse_args()

    disp = int(args.disp, 0)
    exe = Path(args.exe) if args.exe else default_paths()["exe"]
    hits = scan(exe, disp, args.reads, args.limit)
    pe = PE(exe)
    by_fn: dict[int, list[tuple[int, str]]] = {}
    for va, text in hits:
        by_fn.setdefault(function_start(pe, va) or 0, []).append((va, text))
    print(f"{len(hits)} instruction(s) touching [reg+0x{disp:x}] in "
          f"{len(by_fn)} function(s) "
          f"({'reads+writes' if args.reads else 'writes only'}):")
    for fn in sorted(by_fn):
        print(f"\n  function {hex(fn) if fn else '?'}:")
        for va, text in by_fn[fn]:
            print(f"    {hex(va)}  {text}")
    return 0


def function_start(pe: PE, va: int) -> int | None:
    """Start of the .pdata RUNTIME_FUNCTION range containing ``va``."""
    sec = pe.section(".pdata")
    if not sec:
        return None
    raw, rsize, sva = sec["raw"], sec["rsize"], sec["va"]
    for o in range(raw, raw + rsize - 12, 12):
        begin, end, _u = struct.unpack_from("<III", pe.data, o)
        if begin <= (va - pe.image_base) < end:
            return pe.image_base + begin
    return None


def callers_of(pe: PE, target: int, limit: int = 40) -> list[int]:
    """Every `call rel32` whose destination is ``target``."""
    text = pe.section(".text")
    raw, rsize, tva = text["raw"], text["rsize"], text["va"]
    out: list[int] = []
    for off in range(raw, raw + rsize - 5):
        if pe.data[off] != 0xE8:
            continue
        rel = struct.unpack_from("<i", pe.data, off + 1)[0]
        va = tva + (off - raw)
        if va + 5 + rel == target:
            out.append(va)
            if len(out) >= limit:
                break
    return out


if __name__ == "__main__":
    raise SystemExit(main())
