#!/usr/bin/env python3
"""Resolve a wire type to its message name through the client's own hook.

WHY THIS EXISTS
===============
`research/derived/wire-type-names.json` names a wire type by pairing it with a
printable run in `.rdata`, and that heuristic is disproven: it gives the proven
`LevelInfoChangedMsg` GUID no name at all. The reliable method is the client's
own registration hook, whose lambda TypeDescriptor spells both halves of the
pairing:

    .?AV<lambda_1>@?1???$InstallRegistrationHook@V<Message>@<Trait>@@@<Ns>@@YA_NXZ@

`commit b7d106e` walked that chain forwards (name -> wire type). This tool walks
it BACKWARDS, from a wire type to its name, which is the direction that
generalises: given any type id you can ask what it is called, instead of
guessing a name and hoping.

THE CHAIN, and where each link comes from
=========================================
1. wire type W -> `typeindex.json` index W -> the AZ type GUID
2. GUID -> its dashed string in `.rdata` -> its `lea r64,[rip+disp32]` sites
3. `lea` site -> the containing function = the per-message type-record function
4. that function's `call` sites -> the containing function = the lambda body
5. the lambda body's own VA -> an 8-byte pointer to it outside `.text` = the record
6. any record slot that is `48 8d 05 <disp32> c3` is a thunk -> its target is a
   TypeDescriptor, whose `+0x10` is the mangled name

A GUID whose `lea` site sits in a function with no hook record yields NOTHING
rather than a guess. That silence is the point: it is what the adjacency
heuristic cannot do.

`--check` reproduces the two independently proven controls (`0x663` ->
`LevelInfoChangedMsg`, `0x65c` -> `PlayerManagerSelfIdentificationMsg`) and
refuses to write anything if they stop resolving.

Usage:
    python ef.py re message-names --check
    python ef.py re message-names 0x1a59 0x651 0x18a6
    python ef.py re message-names --scan-unresolved --limit 40
    python ef.py re message-names --scan-unresolved --out research/derived/message-names.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import default_paths  # noqa: E402
from catalog import PE  # noqa: E402
from peutil import PEx  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TYPEINDEX = ROOT / "private-client" / "runtime" / "typeindex.json"

# Independently proven before this tool existed; see meanings.md.
CONTROLS = {
    0x663: "LevelInfoChangedMsg",
    0x65C: "PlayerManagerSelfIdentificationMsg",
}

HOOK_MARKER = "InstallRegistrationHook"


def dashed(guid_hex: str) -> str:
    g = guid_hex.replace("-", "")
    return f"{g[0:8]}-{g[8:12]}-{g[12:16]}-{g[16:20]}-{g[20:]}"


def call_map(pe: PE) -> dict[int, list[int]]:
    """callee VA -> VAs of the `call rel32` sites that reach it.

    One pass over .text, but driven by `bytes.find` so the scanning happens at C
    speed; a Python loop over 132 MB takes minutes and this takes seconds.
    """
    text = pe.section(".text")
    data, raw, rsize = pe.data, text["raw"], text["rsize"]
    base_va = text["va"]
    end = raw + rsize - 5
    out: dict[int, list[int]] = {}
    i = data.find(b"\xe8", raw, end)
    while i != -1:
        rel = struct.unpack_from("<i", data, i + 1)[0]
        target = base_va + (i - raw) + 5 + rel
        out.setdefault(target, []).append(base_va + (i - raw))
        i = data.find(b"\xe8", i + 1, end)
    return out


def lea_map(pe: PE) -> dict[int, list[int]]:
    """target VA -> VAs of `lea r64,[rip+disp32]` sites that load it.

    Built ONCE and reused for every wire type. The naive per-query
    `PE.xrefs_to_va` walks .text in Python, which measured 5.07 s per wire type
    on this build (595 min for the whole table). Driving the scan with
    `bytes.find` keeps the work in C: four REX prefixes, then a ModRM check.
    """
    text = pe.section(".text")
    data, raw, rsize = pe.data, text["raw"], text["rsize"]
    base_va = text["va"]
    end = raw + rsize - 7
    out: dict[int, list[int]] = {}
    for rex in (0x48, 0x49, 0x4C, 0x4D):
        pattern = bytes((rex, 0x8D))
        i = data.find(pattern, raw, end)
        while i != -1:
            if (data[i + 2] & 0xC7) == 0x05:
                disp = struct.unpack_from("<i", data, i + 3)[0]
                site_va = base_va + (i - raw)
                target = site_va + 7 + disp
                out.setdefault(target, []).append(site_va)
            i = data.find(pattern, i + 1, end)
    return out


def pointer_sites(pe: PE, value: int) -> list[int]:
    """VAs outside .text that hold an 8-byte little-endian pointer to `value`."""
    text = pe.section(".text")
    lo, hi = text["va"], text["va"] + text["vsize"]
    needle = struct.pack("<Q", value)
    out, i = [], pe.data.find(needle)
    while i != -1:
        va = pe.foff_to_va(i)
        if va is not None and not (lo <= va < hi):
            out.append(va)
        i = pe.data.find(needle, i + 1)
    return out

# A registration table is a run of 48-byte rows. Each row starts with the
# registration lambda's own address, and carries that row's type-descriptor
# thunk at +0x08.
TABLE_ROW = 48

def entry_descriptor(pe: PE, record_va: int, lambda_va: int) -> int | None:
    """The descriptor thunk of the ONE table row that belongs to this lambda.

    WHY THIS EXISTS. `resolve` used to read eight consecutive qwords from the
    table base and treat each as a descriptor of the type being named. A table
    holds many rows, so that reports the neighbours' types too, and 796 of the
    7,052 wire types came out with two or more names for one GUID.

    The row that owns a lambda is the one whose first qword IS that lambda, and
    its own descriptor is that row's second qword. Measured on build 30fe6461:
    applied to all 796 ambiguous types it returns exactly one name for every
    one; on the 2,594 previously-unambiguous types it agrees with the slot scan
    2,576 times and never contradicts it (the other 18 are misses, where this
    returns None and the caller must fall back); and on the 7 replay types with
    independently known names it is correct 7/7, including `0x663` =
    `LevelInfoChangedMsg`, proven separately by decompiling its handler.

    It is therefore a tie-breaker, not a replacement: a None here means "this
    row layout did not apply", not "this type has no name".
    """
    fo = pe.va_to_foff(record_va)
    if fo is None:
        return None
    for row in range(64):
        base = fo + TABLE_ROW * row
        if base + TABLE_ROW > len(pe.data):
            break
        first, descriptor = struct.unpack_from("<QQ", pe.data, base)
        if first == lambda_va:
            return descriptor
    return None


def thunk_target(pe: PE, va: int) -> int | None:
    """`lea rax,[rip+disp32]; ret` -> the address it loads."""
    fo = pe.va_to_foff(va)
    if fo is None:
        return None
    code = pe.data[fo : fo + 7]
    if len(code) == 7 and code[0] == 0x48 and code[1] == 0x8D and (code[2] & 0xC7) == 0x05:
        return va + 7 + struct.unpack_from("<i", pe.data, fo + 3)[0]
    return None


def type_descriptor_name(pe: PE, td: int) -> str | None:
    """A TypeDescriptor is vftable(8) + spare(8) + the mangled name."""
    fo = pe.va_to_foff(td)
    if fo is None:
        return None
    raw = pe.data[fo + 16 : fo + 16 + 512].split(b"\x00")[0]
    return raw.decode("latin-1") if raw else None


def message_from_mangled(mangled: str) -> tuple[str, str] | None:
    """Pull (message, trait) out of an InstallRegistrationHook descriptor."""
    if HOOK_MARKER not in mangled:
        return None
    at = mangled.find(HOOK_MARKER)
    tail = mangled[at:]
    parts = tail.split("@")
    # ... InstallRegistrationHook @ V<Message> @ <Trait> @ <SubNs> @@@ <Ns> @ <Root>
    message = next((p[1:] for p in parts if p.startswith("V") and len(p) > 1), None)
    if not message:
        return None
    idx = parts.index("V" + message) if ("V" + message) in parts else None
    trait = parts[idx + 1] if idx is not None and idx + 1 < len(parts) else ""
    return message, trait


def resolve(px: PEx, calls: dict[int, list[int]], leas: dict[int, list[int]],
            wire: int, index: list[str]) -> dict:
    """Everything this method can say about one wire type, including silence."""
    pe = px.pe
    row: dict = {"wire": f"0x{wire:x}", "index": wire}
    if wire >= len(index):
        row["error"] = "index out of range for this type table"
        return row
    guid = index[wire]
    row["guid"] = dashed(guid)

    # The GUID text appears plain/lowercase or uppercase, and sometimes braced.
    # Both cases, plain and braced: which one the descriptor uses is a property
    # of the build, not of the message. Missing the lowercase plain form is what
    # made this tool silently drop the 0x65c control.
    text_variants = [
        row["guid"],
        row["guid"].lower(),
        row["guid"].upper(),
        "{" + row["guid"].upper() + "}",
        "{" + row["guid"].lower() + "}",
    ]
    hits: list[tuple[int, str]] = []
    for variant in text_variants:
        off = pe.data.find(variant.encode())
        if off != -1:
            va = pe.foff_to_va(off)
            if va is not None:
                hits.append((va, variant))
    row["guid_strings"] = [f"0x{va:x}" for va, _ in hits]
    if not hits:
        row["result"] = "no-guid-string"
        return row

    names: list[dict] = []
    entry_names: list[dict] = []
    for guid_va, variant in hits:
        for site_va in leas.get(guid_va, []):
            rng = px.func_at(site_va)
            if rng is None:
                continue
            record_fn = rng[0]
            for call_site in calls.get(record_fn, []):
                lam = px.func_entry(call_site)
                if lam is None:
                    continue
                for record_va in pointer_sites(pe, lam):
                    fo = pe.va_to_foff(record_va)
                    for slot in range(8):
                        value = struct.unpack_from("<Q", pe.data, fo + 8 * slot)[0]
                        td = thunk_target(pe, value) if value else None
                        if td is None:
                            continue
                        mangled = type_descriptor_name(pe, td)
                        parsed = message_from_mangled(mangled or "")
                        if not parsed:
                            continue
                        names.append(
                            {
                                "name": parsed[0],
                                "trait": parsed[1],
                                "guid_string": f"0x{guid_va:x}",
                                "guid_form": variant,
                                "record_fn": f"0x{record_fn:x}",
                                "lambda": f"0x{lam:x}",
                                "record": f"0x{record_va:x}",
                                "slot": slot,
                                "thunk": f"0x{value:x}",
                                "type_descriptor": f"0x{td:x}",
                                "mangled": mangled,
                            }
                        )
                    # Tie-breaker: the row that owns this lambda, not its
                    # neighbours. See entry_descriptor for the evidence.
                    own = entry_descriptor(pe, record_va, lam)
                    own_td = thunk_target(pe, own) if own else None
                    if own_td is not None:
                        own_mangled = type_descriptor_name(pe, own_td)
                        own_parsed = message_from_mangled(own_mangled or "")
                        if own_parsed:
                            entry_names.append(
                                {
                                    "name": own_parsed[0],
                                    "trait": own_parsed[1],
                                    "guid_string": f"0x{guid_va:x}",
                                    "guid_form": variant,
                                    "record_fn": f"0x{record_fn:x}",
                                    "lambda": f"0x{lam:x}",
                                    "record": f"0x{record_va:x}",
                                    "slot": -1,
                                    "thunk": f"0x{own:x}",
                                    "type_descriptor": f"0x{own_td:x}",
                                    "mangled": own_mangled,
                                }
                            )
    # Deduplicate: one GUID can be reachable from more than one site.
    seen, unique = set(), []
    for n in names:
        if n["name"] in seen:
            continue
        seen.add(n["name"])
        unique.append(n)
    # A single owner wins over the slot scan. More than one distinct owner means
    # the table layout did not resolve here, and the candidate list is honest.
    entry_seen, entry_unique = set(), []
    for n in entry_names:
        if n["name"] in entry_seen:
            continue
        entry_seen.add(n["name"])
        entry_unique.append(n)
    if len(entry_unique) == 1:
        row["resolution"] = "entry-match"
        row["candidates"] = [n["name"] for n in unique]
        row["names"] = entry_unique
    else:
        row["resolution"] = "slot-scan" if unique else "none"
        row["names"] = unique
    row["result"] = "named" if row["names"] else "no-hook-record"
    return row


def load_index() -> list[str]:
    data = json.loads(TYPEINDEX.read_text(encoding="utf-8"))
    return [str(g).replace("-", "").upper() for g in data["typeIndex"]]


def check(px: PEx, calls: dict[int, list[int]], leas: dict[int, list[int]], index: list[str]) -> int:
    print(f"controls against build {hashlib.sha256(px.pe.data).hexdigest()[:16]}")
    bad = 0
    for wire, want in CONTROLS.items():
        row = resolve(px, calls, leas, wire, index)
        got = [n["name"] for n in row.get("names", [])]
        ok = want in got
        print(f"  {'PASS' if ok else 'FAIL'} 0x{wire:x} -> {got or 'nothing'} (want {want})")
        bad += 0 if ok else 1
    print("check:", "OK" if not bad else "FAILED")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("wires", nargs="*", help="wire types, e.g. 0x1a59")
    ap.add_argument("--check", action="store_true", help="verify the proven controls")
    ap.add_argument("--scan-unresolved", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out")
    args = ap.parse_args()

    exe = default_paths()["exe"]
    px = PEx(exe)
    pe = px.pe
    index = load_index()
    print(f"[names] build {hashlib.sha256(pe.data).hexdigest()[:16]} type table {len(index)}", file=sys.stderr)

    if args.check:
        return check(px, call_map(pe), lea_map(pe), index)

    calls = call_map(pe)
    leas = lea_map(pe)
    print(f"[names] call map: {len(calls)} callees, lea map: {len(leas)} targets", file=sys.stderr)

    if args.scan_unresolved:
        rows = []
        for wire in range(len(index)):
            rows.append(resolve(px, calls, leas, wire, index))
        named = [r for r in rows if r.get("result") == "named"]
        silent = [r for r in rows if r.get("result") == "no-hook-record"]
        other = [r for r in rows if r.get("result") not in ("named", "no-hook-record")]
        print(
            f"[names] {len(rows)} wire types: {len(named)} named by hook, "
            f"{len(silent)} no hook record, {len(other)} no guid string"
        )
        if args.limit:
            silent = silent[: args.limit]
        for r in silent:
            print(f"  silent 0x{int(r['wire'], 16):<6x} index {r['index']:<5} {r['guid']}")
        if args.out:
            payload = {
                "build_sha256": hashlib.sha256(pe.data).hexdigest(),
                "wire_types": len(rows),
                "named": len(named),
                "rows": rows,
            }
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"[names] wrote {out}")
        return 0

    if not args.wires:
        ap.error("give at least one wire type, or --check, or --scan-unresolved")
    rc = 0
    for raw in args.wires:
        wire = int(raw, 16) if raw.lower().startswith("0x") else int(raw)
        row = resolve(px, calls, leas, wire, index)
        print(json.dumps(row, indent=2))
        if row["result"] != "named":
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
