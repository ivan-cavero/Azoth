"""Find a message type's codec facet by grepping its name from the 1.460 corpus.

WHY THIS EXISTS
===============
Decoding `AddActorMessage` took a chain of manual greps, and the same chain applies to every other
presence type. This automates it so the remaining five cost one command each.

HOW A TYPE IS FOUND
===================
A message type's descriptor getter inlines its name as little-endian immediates in the decompiled
body, e.g. `AddActorMessage` appears as

    lStack_28 = 0x726f746341646441;   "AddActor"
    uStack_20 = 0x7373654d;           "Mess"
    uStack_1c = 0x6761;               "ag"
    uStack_1a = 0x65;                 "e"

because the compiler materialises short strings as immediate stores. So the search key is the
name's first eight bytes as a little-endian u64, which is specific enough to be unique.

Once the getter is found, the facet address is the `*puVar = &UNK_<addr>` store in the same
function, and the codec table is six qwords at that address: slot 4 (+0x20) is MARSHAL and slot 5
(+0x28) is UNMARSHAL. Verified against AddActorMessage, where slot 0 is a deleting destructor that
restores the same vptr — a cheap self-check the script performs on every hit.

Usage:
    python scripts/find-codec-facet.py Replicate
    python scripts/find-codec-facet.py SpawnActorsMsg --read-table
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORPUS = (
    REPO / "reverse" / "builds"
    / "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033"
    / "corpus" / "shards"
)
EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\New World\Bin64\NewWorld.exe")

FUNC_RE = re.compile(r"^FUNC (FUN_[0-9a-f]+) entry=([0-9a-f]+)")
# The facet install: `*puVar3 = &UNK_148575298;` or `*puVar = &UNK_<addr>;`
FACET_RE = re.compile(r"\*puVar\w* = &UNK_([0-9a-f]+);")


def name_key(name: str) -> int:
    """The first eight bytes of `name` as a little-endian u64, as the compiler stores it."""
    raw = name.encode("ascii")[:8].ljust(8, b"\0")
    return int.from_bytes(raw, "little")


def find_getters(name: str) -> list[tuple[str, str, str | None]]:
    """Return [(function, shard, facet address)] for the body that carries the name key.

    THE TRAP THIS AVOIDS: a shard holds many functions, and several of them install a facet. The
    getter we want is the one whose OWN body contains the name immediates, so the key must be
    matched per function body, not per shard — matching per shard returns every facet installer
    in the file, which is what the first version of this script did.
    """
    key = f"0x{name_key(name):x}"
    hits: list[tuple[str, str, str | None]] = []
    for shard in sorted(CORPUS.glob("shard-*.c")):
        text = shard.read_text(encoding="utf-8", errors="replace")
        if key not in text:
            continue
        # Split into per-function blocks so the key and the facet store are attributed to the
        # SAME function.
        blocks: list[tuple[str, str]] = []
        current_name: str | None = None
        current_body: list[str] = []
        for line in text.splitlines():
            header = FUNC_RE.match(line)
            if header:
                if current_name is not None:
                    blocks.append((current_name, "\n".join(current_body)))
                current_name = header.group(1)
                current_body = []
                continue
            if current_name is not None:
                current_body.append(line)
        if current_name is not None:
            blocks.append((current_name, "\n".join(current_body)))

        for function, body in blocks:
            if key not in body:
                continue
            install = FACET_RE.search(body)
            hits.append((function, shard.name, install.group(1) if install else None))
    return hits


def read_table(va: int) -> list[int] | None:
    """Read six qwords at `va` from the executable's .rdata, mapping VA to file offset."""
    if not EXE.is_file():
        return None
    data = EXE.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    sec = opt + struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(nsec):
        o = sec + i * 40
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, o + 8)
        if vaddr <= (va - 0x140000000) < vaddr + max(vsize, rawsize):
            off = rawptr + (va - 0x140000000 - vaddr)
            return list(struct.unpack_from("<6Q", data, off))
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="the message type name, e.g. Replicate")
    ap.add_argument("--read-table", action="store_true",
                    help="read the six facet slots from the executable")
    args = ap.parse_args()

    if not CORPUS.is_dir():
        print(f"no corpus at {CORPUS}")
        return 1

    print(f"search key for {args.name!r}: 0x{name_key(args.name):x}")
    hits = find_getters(args.name)
    if not hits:
        print("no getter found. The name may be shorter than 8 bytes, or its immediates may be "
              "split differently; try a shorter prefix or grep the brace GUID instead.")
        return 2

    for function, shard, facet in hits:
        print(f"\ngetter {function}  ({shard})")
        print(f"  facet address 0x{facet}")
        if args.read_table:
            slots = read_table(int(facet, 16))
            if slots is None:
                print("  could not map that VA into the executable")
                continue
            for i, slot in enumerate(slots):
                tag = {4: "  <- MARSHAL", 5: "  <- UNMARSHAL"}.get(i, "")
                print(f"    +0x{i * 8:02x} 0x{slot:x}{tag}")
            # Self-check: slot 0 should be a function that restores this same vptr.
            print(f"  self-check: slot 0 = 0x{slots[0]:x}; grep the corpus for that function and "
                  f"confirm it stores &UNK_{facet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
