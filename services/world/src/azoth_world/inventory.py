"""Server-owned inventory: the server decides what the player has, and the client shows it.

WHY THIS MODULE EXISTS
=====================
The client asks for its inventories and the server answers with a captured body, replayed verbatim.
This module is the first place the server owns that answer: it can read the captured entries and emit
a different list.

THE RESPONSE, MEASURED 2026-10-19
=================================
`InventoriesComponentClientFacet_OnQueryInventories` (wire `0x16a0`) has TWO captured bodies:
**153 B** (the empty form, no entries) and **99 819 B** (the populated one). The body is

    [00 01][a0 5a][16-byte target][01][varint 0x16c4][...]  then  entry × N

**427 entries** in the populated form.

THE ENTRY
=========
Every entry contains the marker `00 01 82 5a` at a fixed offset, and the entry starts **68 bytes
before** it. Inside an entry, in order:

    container name   NUL-padded, starts at the entry start        ("w-world|")
    marker           00 01 82 5a
    u32 BE           zero in every captured entry (reserved)
    u8               length of the type name
    type name        that many bytes                              ("SkinCollection")
    16 bytes         item GUID
    4 bytes          flags
    literal          "isCollected"
    4 bytes          count (1 in every captured entry)
    0x02             a tag, not a length
    1 byte           id length
    char[..]         item id as DECIMAL ASCII                     ("1027224182")

RE-MEASURED ON THE 1.460 CORPUS, 2026-10-22
===========================================
`scripts/measure-inventory-grammar.py` re-reads the committed block and confirms the numbers
above: the empty form is **153 B**, the populated form is **99,819 B**, it holds **427 entries**
(428 marker occurrences, 427 gaps), `marker - 68` lands exactly on the NUL-padded container name,
and the marker-to-marker gaps span **231..233 B** (427 distinct gaps: 233 x338, 232 x79, 231 x10).

The one correction is the field after the marker: it is a **zero u32 followed by a `u8` length**,
not a u32 length. Measured on the first entry, `marker + 4` is `00 00 00 00` and `marker + 8` is
`0e` (14), which is exactly `len("SkinCollection")`. The docstring previously described the
length as a u32, which would read 0 and make the type name empty.

THE SIZE VARIES, AND THAT IS THE TRAP
=====================================
An entry is **223 + id_length** bytes: measured **233** for a 10-digit id (338 entries), **232** for
9 digits (79), **231** for 8 digits (10). A parser that assumes a fixed stride reads 19 of 427 entries
correctly and then walks into padding - which is what the first attempt did. So the walk anchors on
the MARKER, never on an index.

THE DESIGN: CARRY THE CAPTURED ENTRY, PATCH THE ID
==================================================
Rather than reconstruct an entry field by field - which would require inventing the semantics of
`0x02`, of the flags, and of whether the numeric id is a key or a counter - an entry is kept as its
**captured bytes** and the server patches only what it understands. That is the same method that
produced the first authoritative effect for the player (2026-10-14, 0.0000 u) and it has a decisive
property: **re-encoding an unmodified entry is byte-identical to the capture**, which the tests assert
over all 427 entries.

WHAT IS DELIBERATELY NOT DONE
=============================
The MEANING of the fields is not decoded. The module can read them and write the id; it does not claim
to know what a flag bit does.
"""

from __future__ import annotations

from dataclasses import dataclass

# MEASURED 2026-10-19 from the committed replay (seq 0x29, 99819 bytes).
ENTRY_MARKER = bytes.fromhex("0001825a")
MARKER_OFFSET = 68
"""The entry starts this many bytes before its marker."""
ENTRIES_START = 100
"""First entry's offset in the captured body: the header ends here."""
FLAG_NAME = b"isCollected"


@dataclass(frozen=True)
class ItemEntry:
    """One inventory entry, held as its captured bytes plus the fields the server understands.

    ``raw`` is the entry exactly as captured. The properties read fields out of it by literal search,
    which is what makes the read robust to the offsets this module does not want to hardcode.
    """

    raw: bytes

    @property
    def container(self) -> bytes:
        """The container name, which is the leading NUL-padded field."""
        return self.raw.split(b"\x00", 1)[0]

    @property
    def type_name(self) -> bytes:
        """The item type name: a varint length four bytes after the marker, then the bytes.

        MEASURED 2026-10-19: the marker ends at +72, then **four zero bytes**, then a varint length at
        +76 and the name at +77. The four zeros are why a u32 read at +72 returns 0 - that was the
        first, wrong reading.
        """
        from .javelin.varint import decode as varint_decode, VarintError

        at = self.raw.find(ENTRY_MARKER)
        if at < 0:
            return b""
        # Skip the zero padding between the marker and the length varint, rather than assuming a
        # fixed gap: measured as four zero bytes, but the padding is not a documented field.
        length_at = at + len(ENTRY_MARKER)
        while length_at < len(self.raw) and self.raw[length_at] == 0:
            length_at += 1
        try:
            # `decode` returns (value, NEXT OFFSET), not (value, width). Treating the second element
            # as a width reads 77 bytes past the length byte and returns zeros - the same API mistake
            # that was caught in the movement reader.
            length, name_at = varint_decode(self.raw, length_at)
        except VarintError:
            return b""
        return self.raw[name_at:name_at + length]

    @property
    def item_id(self) -> bytes:
        """The item id, the decimal ASCII digits at the end of the entry."""
        digits = bytearray()
        for byte in reversed(self.raw):
            if 48 <= byte <= 57:
                digits.append(byte)
            elif digits:
                break
        return bytes(reversed(digits))

    @property
    def id_text(self) -> str:
        return self.item_id.decode("ascii", "replace")

    def with_id(self, new_id: str) -> "ItemEntry":
        """A copy of this entry carrying a different id, with the length byte updated.

        The entry's size follows the id's length, so the length byte and the digits are rewritten
        together - a body where only one of them changed is a body the client would not produce.
        """
        encoded = new_id.encode("ascii", "replace")
        old = self.item_id
        if not old:
            return self
        # The old id sits immediately before the trailing padding.
        at = self.raw.rfind(old)
        if at < 0:
            return self
        length_at = at - 1
        if self.raw[length_at] != len(old):
            return self
        head = self.raw[:length_at]
        tail = self.raw[at + len(old):]
        return ItemEntry(head + bytes((len(encoded),)) + encoded + tail)


def split_entries(body: bytes) -> list[ItemEntry]:
    """Every entry the body carries, walked by MARKER so a variable size cannot derail it.

    Returns an empty list for the 153-byte empty form, which carries no marker.
    """
    starts: list[int] = []
    at = body.find(ENTRY_MARKER)
    while at >= 0:
        start = at - MARKER_OFFSET
        if start < 0:
            break
        starts.append(start)
        at = body.find(ENTRY_MARKER, at + len(ENTRY_MARKER))
    entries: list[ItemEntry] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(body)
        entries.append(ItemEntry(body[start:end]))
    return entries


def render_body(template: bytes, entries: list[ItemEntry]) -> bytes:
    """Build a response body from a captured template and a list of entries.

    The template supplies the header the client expects; only the entry region is replaced, so every
    undecoded header byte stays exactly as the client produced it.
    """
    return template[:ENTRIES_START] + b"".join(entry.raw for entry in entries)
