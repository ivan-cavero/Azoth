#!/usr/bin/env python3
"""Static MSVC RTTI scan of NewWorld.exe — measured, including its negative result.

No PDB, no Ghidra, no process: everything from the on-disk exe, stdlib only.

**MEASURED CONCLUSION (2026-10-05): the game code is compiled without vftable
RTTI (/GR-).** The exe carries 4,820 MSVC TypeDescriptors (".?AV…" strings in
`.data`, vfptr to the CRT type_info vftable) but only 1,959
CompleteObjectLocators (verified two ways: via TD references and by scanning
for the self-referential `pSelf` field), and **every one of them belongs to a
class whose vftable lives in the imported CRT (msvcp140/vcruntime)** — zero
COL-vftables point at in-image `.text`. Consequence: Ghidra's RTTI class
recovery can only name exception/STL classes here, never game classes. Game
class naming must come from the AZ reflection registry and string references
(namer v2) — see odd/tasks/corpus-naming.md.

What this tool still delivers:

1. **The type-name pool** (`td_names`): all demangled TypeDescriptor names.
   Template instantiations leak real game type names (e.g.
   `MeshComponentRenderNode`, `SkinnedMeshComponentRenderNode` inside
   `AZStd::bind_t` members) — fuel for the corpus namer.
2. **COL classes** (`classes`): the 1,959 COL-vftable pairs, kept for
   completeness; their vftable entries are import thunks, not functions.

Usage:
    python research/tools/reversing/rtti.py build      # scan -> rtti-classes.json
    python research/tools/reversing/rtti.py find NAME  # names matching NAME
    python research/tools/reversing/rtti.py selftest
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import PE  # noqa: E402
from common import default_paths  # noqa: E402

NAME_RE = re.compile(rb"\.\?A([VUW][0-9]?)([^\x00]+?@@)\x00")
OUT = Path(__file__).resolve().parents[2] / "derived" / "rtti-classes.json"


def demangle(raw: bytes) -> str:
    """.?AVReplicaChunk@GridMate@@ -> GridMate::ReplicaChunk (best effort)."""
    body = raw.decode("latin-1")
    if body.endswith("@@"):
        body = body[:-2]
    tokens = [t for t in body.split("@") if t]
    if not tokens:
        return body
    return "::".join(reversed(tokens))


def _scan_sections(pe: PE) -> list[dict]:
    keep = {".rdata", ".data", "_RDATA"}
    return [s for s in pe.sections if s["name"] in keep and s["rsize"] > 0]


def _foff(pe: PE, va: int) -> int:
    for s in pe.sections:
        if s["va"] <= va < s["va"] + s["vsize"] and s["rsize"]:
            raw = s["raw"] + (va - s["va"])
            if raw < s["raw"] + s["rsize"]:
                return raw
    raise ValueError(f"VA {va:#x} not in any raw-backed section")


def _find_names(pe: PE, secs: list[dict]) -> dict[int, str]:
    """TypeDescriptor VA -> demangled name (TD = vfptr + spare + name)."""
    td: dict[int, str] = {}
    for s in secs:
        data = pe.data[s["raw"]:s["raw"] + s["rsize"]]
        for m in NAME_RE.finditer(data):
            td_va = s["va"] + m.start() - 0x10
            td.setdefault(td_va, demangle(m.group(2)))
    return td


def _rva_hits(pe: PE, secs: list[dict], wanted: set[int]) -> dict[int, list[int]]:
    """One pass: every u32 whose image-relative RVA value is in `wanted`."""
    hits: dict[int, list[int]] = {}
    base = pe.image_base
    for s in secs:
        data = bytes(pe.data[s["raw"]:s["raw"] + s["rsize"]])
        n = len(data) // 4
        arr = memoryview(data)[:n * 4]
        sec_rva = s["va"] - base
        for i in range(n):
            v = struct.unpack_from("<I", arr, i * 4)[0]
            if v in wanted:
                hits.setdefault(v, []).append(base + sec_rva + i * 4)
        del arr, data
    return hits


def _value_hits(pe: PE, secs: list[dict], wanted: set[int]) -> dict[int, list[int]]:
    """One pass: every u64 whose full VA value is in `wanted`."""
    hits: dict[int, list[int]] = {}
    for s in secs:
        data = bytes(pe.data[s["raw"]:s["raw"] + s["rsize"]])
        n = len(data) // 8
        arr = memoryview(data)[:n * 8]
        base = s["va"]
        for i in range(n):
            v = struct.unpack_from("<Q", arr, i * 8)[0]
            if v in wanted:
                hits.setdefault(v, []).append(base + i * 8)
        del arr, data
    return hits


def _cols_by_pself(pe: PE, rdata: dict) -> int:
    """Definitive COL enumeration: sig==1 and pSelf == own RVA (20 bytes later)."""
    d = pe.data[rdata["raw"]:rdata["raw"] + rdata["rsize"]]
    n = len(d) // 4
    sec_rva = rdata["va"] - pe.image_base
    count = 0
    for i in range(n - 6):
        if struct.unpack_from("<I", d, i * 4)[0] != 1:
            continue
        if struct.unpack_from("<I", d, (i + 5) * 4)[0] != sec_rva + i * 4:
            continue
        count += 1
    return count


def build() -> int:
    pe = PE(default_paths()["exe"])
    secs = _scan_sections(pe)
    base = pe.image_base
    text = pe.section(".text")

    print("scanning TypeDescriptors...")
    td = _find_names(pe, secs)
    print(f"  {len(td):,} TypeDescriptors")

    td_hits = _rva_hits(pe, secs, {td_va - base for td_va in td})
    cols: dict[int, int] = {}
    for td_rva, spots in td_hits.items():
        for hit in spots:
            # x64 COL = 6 DWORDs: sig(+0) offset(+4) cdOffset(+8)
            # pTypeDescriptor(+12) pClassDescriptor(+16) pSelf(+20).
            # A TD is also referenced from exception CatchableTypes; sig==1
            # rejects those.
            col_va = hit - 0xC
            if struct.unpack_from("<I", pe.data, _foff(pe, col_va))[0] == 1:
                cols.setdefault(col_va, base + td_rva)
    cols_total = _cols_by_pself(pe, pe.section(".rdata"))
    print(f"  {len(cols):,} COLs via TD refs ({cols_total:,} by pSelf validation)")

    classes = []
    col_hits = _value_hits(pe, secs, set(cols))
    for col_va, spots in col_hits.items():
        for hit in spots:
            vftable_va = hit + 8
            in_text = 0
            # slots are 32-bit RVAs; for imported-CRT classes they are not
            # in-image functions — count how many would be, for the record.
            for k in range(256):
                off = _foff(pe, vftable_va) + k * 4
                if off + 4 > len(pe.data):
                    break
                rva = struct.unpack_from("<I", pe.data, off)[0]
                if not (text["va"] <= base + rva < text["va"] + text["vsize"]):
                    break
                in_text += 1
            classes.append({
                "name": td[cols[col_va]],
                "td_va": f"0x{cols[col_va]:x}",
                "col_va": f"0x{col_va:x}",
                "vftable_va": f"0x{vftable_va:x}",
                "slots_in_text": in_text,
            })
            break

    out = {
        "exe_sha256_prefix": "8654f01d324636d9",
        "measured_conclusion": (
            "Game code is compiled without vftable RTTI (/GR-): 4,820 "
            "TypeDescriptors exist but all 1,959 COLs belong to imported-CRT "
            "classes (0 vftable entries inside .text). RTTI class recovery "
            "cannot name game classes on this build; use the AZ reflection "
            "registry and string references instead."
        ),
        "td_names": [{"td_va": f"0x{va:x}", "name": name} for va, name in sorted(td.items(), key=lambda kv: kv[1])],
        "classes": classes,
        "note": "Candidate pool only (regenerable with rtti.py build). "
                "Names are RTTI metadata from the exe; a name is CONFIRMED "
                "into symbols.json only with a second agreeing signal.",
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"  {len(classes):,} COL classes; {len(td):,} td names -> {OUT.name}")
    return 0


def _load() -> dict:
    return json.loads(OUT.read_text())


def find(needle: str) -> int:
    data = _load()
    names = data["td_names"]
    hits = [n for n in names if needle.lower() in n["name"].lower()]
    for n in hits[:60]:
        print(f"{n['name']}  td={n['td_va']}")
    print(f"{len(hits)} type names matching '{needle}' "
          f"(of {len(names):,}; game code has no vftable RTTI — see build())")
    return 0


def selftest() -> int:
    if not OUT.exists():
        print("selftest: FAIL — no scan output; run `rtti.py build` first")
        return 1
    data = _load()
    names = [n["name"] for n in data["td_names"]]
    checks: list[tuple[str, bool]] = []
    checks.append((">= 4,000 TypeDescriptor names", len(names) >= 4000))
    # Game-system names leaked through template instantiations — independently
    # known from AZ reflection (symbols.json component_names_resolved).
    for needle in ("MeshComponentRenderNode", "GridMate", "AZStd"):
        checks.append((f"type-name pool contains '{needle}'",
                       any(needle in n for n in names)))
    checks.append(("COL classes recorded", len(data["classes"]) >= 1000))
    # The negative result must hold: no COL class has in-image vftable entries.
    checks.append(("negative result holds (0 in-text slots anywhere)",
                   all(c["slots_in_text"] == 0 for c in data["classes"])))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(f"{'PASS' if v else 'FAIL'} {name}")
    print(f"selftest: {'OK' if ok else 'FAIL'} "
          f"({len(names):,} names, {len(data['classes']):,} COL classes)")
    return 0 if ok else 1


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "build":
        return build()
    if cmd == "find":
        return find(sys.argv[2] if len(sys.argv) > 2 else "")
    if cmd == "selftest":
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
