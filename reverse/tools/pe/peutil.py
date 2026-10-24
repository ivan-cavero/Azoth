#!/usr/bin/env python3
"""PE helpers for targeted RE on NewWorld.exe.

Thin layer over `catalog.PE` (sections, VA<->file offset, string reads) adding the
three things you actually need to aim a decompiler at a specific place:

* `ranges` / `func_at`  — exact function boundaries from `.pdata`
  (RUNTIME_FUNCTION[] = {BeginRVA, EndRVA, UnwindRVA}, 12 bytes each). Ghidra and
  our own decompile helper need a start AND an end; a raw xref offset is not a
  function entry.
* `callers_of`          — direct `call rel32` sites, so you can walk up from a
  leaf helper to the code that decides something.
* `string_at` / `find_string` — resolve a VA to its text and vice versa, which is
  how you turn "this key is read at 0x144f54d63" into "the property is
  `publicStatusCode`".

Disk only. Never touches the running game process (see reverse/tools/memory.py).

Usage:
    python reverse/tools/peutil.py func 0x144f54d63
    python reverse/tools/peutil.py callers 0x1417c40a0
    python reverse/tools/peutil.py str publicStatusCode
    python reverse/tools/peutil.py resolve 0x1483c09a0
    python reverse/tools/peutil.py selftest
"""

from __future__ import annotations

import bisect
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402


class PEx:
    """PE + function table + caller scan for one binary."""

    def __init__(self, path: Path) -> None:
        self.pe = PE(path)
        self._ranges: list[tuple[int, int]] | None = None
        self._starts: list[int] = []

    # ---------------------------------------------------------- functions

    @property
    def ranges(self) -> list[tuple[int, int]]:
        """Sorted (start, end) function ranges from .pdata."""
        if self._ranges is None:
            pd = self.pe.section(".pdata")
            n = pd["rsize"] // 12
            out = []
            for i in range(n):
                b, e, _ = struct.unpack_from("<III", self.pe.data, pd["raw"] + i * 12)
                out.append((self.pe.image_base + b, self.pe.image_base + e))
            out.sort()
            self._ranges = out
            self._starts = [s for s, _ in out]
        return self._ranges

    def func_at(self, va: int) -> tuple[int, int] | None:
        """Function range containing va (binary search over .pdata)."""
        r = self.ranges
        i = bisect.bisect_right(self._starts, va) - 1
        if i < 0:
            return None
        s, e = r[i]
        return (s, e) if s <= va < e else None

    def func_entry(self, va: int) -> int | None:
        r = self.func_at(va)
        return r[0] if r else None

    # ------------------------------------------------------------ callers

    def callers_of(self, target_va: int) -> list[int]:
        """VAs of direct `call rel32` instructions targeting target_va."""
        text = self.pe.section(".text")
        data = self.pe.data
        base_va, raw, rsize = text["va"], text["raw"], text["rsize"]
        out = []
        for i in range(raw, raw + rsize - 5):
            if data[i] != 0xE8:
                continue
            rel = struct.unpack_from("<i", data, i + 1)[0]
            if base_va + (i - raw) + 5 + rel == target_va:
                out.append(base_va + (i - raw))
        return out

    def caller_funcs(self, target_va: int) -> list[tuple[int, int]]:
        """Deduplicated function ranges that call target_va."""
        seen, out = set(), []
        for c in self.callers_of(target_va):
            r = self.func_at(c)
            if r and r not in seen:
                seen.add(r)
                out.append(r)
        return out

    # ------------------------------------------------------------ strings

    def string_at(self, va: int, limit: int = 200) -> str:
        fo = self.pe.va_to_foff(va)
        return self.pe.cstring_at(fo, limit) if fo is not None else ""

    def find_string(self, needle: str, nul_terminated: bool = True) -> list[int]:
        """VAs of occurrences of needle (NUL-terminated by default)."""
        raw = needle.encode("latin-1", "replace")
        if nul_terminated:
            raw += b"\0"
        out = []
        for fo in self.pe.find_all(raw):
            va = self.pe.foff_to_va(fo)
            if va is not None:
                out.append(va)
        return out

    def resolve(self, va: int) -> str:
        """Human label for an address: a string if it points at text, else a func."""
        s = self.string_at(va, 80)
        if s and all(32 <= ord(c) < 127 for c in s):
            return repr(s)
        r = self.func_at(va)
        if r:
            return f"FUN_{r[0]:x}"
        return "?"


def _open() -> PEx:
    return PEx(default_paths()["exe"])


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="PE helpers for targeted RE")
    ap.add_argument(
        "cmd", choices=["func", "callers", "str", "resolve", "selftest", "info"]
    )
    ap.add_argument("arg", nargs="?")
    args = ap.parse_args()
    pex = _open()

    if args.cmd == "info":
        print(f"exe: {pex.pe.path}")
        print(f"image_base: {hex(pex.pe.image_base)}")
        print(f"functions (.pdata): {len(pex.ranges)}")
        for s in pex.pe.sections:
            print(
                f"  {s['name']:8s} VA={hex(s['va'])} vsize={hex(s['vsize'])} raw={hex(s['raw'])}"
            )
        return 0

    if args.cmd == "func":
        va = int(args.arg, 16)
        r = pex.func_at(va)
        print(
            f"{hex(va)} -> "
            + (
                f"{hex(r[0])}-{hex(r[1])} ({r[1] - r[0]} bytes)"
                if r
                else "no .pdata range"
            )
        )
        return 0

    if args.cmd == "callers":
        va = int(args.arg, 16)
        cs = pex.callers_of(va)
        print(f"{len(cs)} callers of {hex(va)}:")
        for c in cs:
            r = pex.func_at(c)
            print(f"  @{hex(c)}  in {hex(r[0])}-{hex(r[1])}" if r else f"  @{hex(c)}")
        return 0

    if args.cmd == "str":
        for va in pex.find_string(args.arg)[:8]:
            r = pex.func_at(va)
            print(f"  {hex(va)}  (in data; no func)")
        return 0

    if args.cmd == "resolve":
        print(f"{hex(int(args.arg, 16))} -> {pex.resolve(int(args.arg, 16))}")
        return 0

    # selftest: invariants that must hold, using facts already established by RE.
    checks = []
    r = pex.func_at(0x144F54D63)
    checks.append(
        (
            "func_at(publicStatusCode xref) is a range",
            r is not None and r[0] == 0x144F40780,
        )
    )
    checks.append(
        (
            "resolve(0x1483c09a0) == 'publicName'",
            pex.resolve(0x1483C09A0) == "'publicName'",
        )
    )
    checks.append(
        (
            "resolve(0x1483c0988) == 'publicStatusCode'",
            pex.resolve(0x1483C0988) == "'publicStatusCode'",
        )
    )
    checks.append(
        ("WorldType mapper has 4 callers", len(pex.callers_of(0x1417C40A0)) == 4)
    )
    checks.append(
        (
            "func_entry inside big parser == 0x144f40780",
            pex.func_entry(0x144F55461) == 0x144F40780,
        )
    )
    checks.append(
        ("find_string('OpenWorld') non-empty", len(pex.find_string("OpenWorld")) > 0)
    )
    ok = True
    for name, good in checks:
        print(("PASS " if good else "FAIL ") + name)
        ok &= good
    print("selftest:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
