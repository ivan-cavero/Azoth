"""Verify the inventory response's entry grammar against the captured populated body.

WHY THIS EXISTS
===============
The Rust port must originate `InventoriesComponentClientFacet_OnQueryInventories` (wire
0x16a0) instead of replaying a captured body, and inventory.py's docstring describes the
entry layout from a body it never re-checked. This reads the two captured bodies straight
out of the committed replay corpus and measures the grammar, so the port has a number to
assert against rather than a description to trust.

Two captured forms exist and both matter:
  * seq 0x28, 153 bytes  -- the EMPTY form, which a live 1.460 session received;
  * seq 0x29, 99819 bytes -- the POPULATED form, 427 entries.

Usage:
    python scripts/measure-inventory-grammar.py
"""

from __future__ import annotations

import re
import struct
import sys
from collections import Counter
from pathlib import Path

REPLAY = Path(__file__).resolve().parents[2] / "services" / "world" / "replay" / "messages-redacted.txt"

# The per-entry marker inventory.py records.
ENTRY_MARKER = bytes.fromhex("0001825a")
# inventory.py: "the entry starts 68 bytes before it".
ENTRY_START_BACK = 68


def load_blocks(path: Path) -> dict[str, bytes]:
    """Return {file name: raw bytes} for every block in the replay dump.

    The dump is a text hexdump with `XX` where the capture was redacted, so a block's
    bytes are recoverable only up to the redaction; the offset column makes the gaps
    explicit, which is why they are honoured rather than compacted.
    """
    blocks: dict[str, bytes] = {}
    name = None
    want = False
    buf = bytearray()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^file: (\S+)", line)
        if m:
            if name is not None:
                blocks[name] = bytes(buf)
            name = m.group(1)
            buf = bytearray()
            want = False
            continue
        if line.startswith("raw:"):
            want = True
            continue
        if want:
            # A classic hexdump puts an EXTRA space between the eighth and ninth
            # byte groups. A parser that allows only single spaces between pairs
            # captures half of each line and silently zero-pads the rest — which
            # is what the first version of this function did, producing a
            # plausible-looking but wrong byte string that then "refuted" a
            # documented layout. Take everything between the offset and the ASCII
            # column, then strip all whitespace.
            m = re.match(r"^([0-9a-f]{8})  (.+?)\s*\|", line)
            if not m:
                if line.strip() == "":
                    continue
                want = False
                continue
            off = int(m.group(1), 16)
            hexpart = m.group(2).replace(" ", "")
            if len(hexpart) % 2:
                hexpart = hexpart[:-1]
            # A redacted byte is not recoverable; pad with 0x00 so offsets stay aligned
            # and count them, because a redacted region invalidates any length claim
            # that crosses it.
            while len(buf) < off:
                buf.append(0)
            for i in range(0, len(hexpart), 2):
                pair = hexpart[i:i + 2]
                buf.append(0 if "X" in pair else int(pair, 16))
    if name is not None:
        blocks[name] = bytes(buf)
    return blocks


def main() -> int:
    blocks = load_blocks(REPLAY)
    for key in ("0x28_T0x16a0_R.bin", "0x29_T0x16a0_R.bin"):
        body = blocks.get(key)
        if body is None:
            print(f"{key}: NOT FOUND in the corpus")
            continue
        print(f"===== {key}: {len(body)} bytes")
        print(f"   head: {body[:32].hex()}")
        positions = []
        start = 0
        while True:
            i = body.find(ENTRY_MARKER, start)
            if i < 0:
                break
            positions.append(i)
            start = i + 1
        print(f"   entry markers ({ENTRY_MARKER.hex()}): {len(positions)}")
        if not positions:
            continue
        gaps = [b - a for a, b in zip(positions, positions[1:])]
        print(f"   marker-to-marker gaps: {len(gaps)} distinct, "
              f"min {min(gaps) if gaps else 0}, max {max(gaps) if gaps else 0}, "
              f"most common {Counter(gaps).most_common(3)}")
        # The entry start claim: 68 bytes before the marker.
        starts = [p - ENTRY_START_BACK for p in positions]
        print(f"   claimed entry start (marker - {ENTRY_START_BACK}): "
              f"first {starts[0]}, min {min(starts)}, negatives "
              f"{sum(1 for s in starts if s < 0)}")
        # What is at the claimed start? inventory.py says a NUL-padded container name.
        sample = body[starts[0]:positions[0]] if starts[0] >= 0 else b""
        print(f"   bytes at the first claimed start: {sample[:48]!r}")
        # The u32 BE type-name length and the name, immediately after the marker.
        i = positions[0]
        nlen = struct.unpack(">I", body[i + 4:i + 8])[0]
        name = body[i + 8:i + 8 + nlen]
        print(f"   type-name length after marker: {nlen}  name: {name[:60]!r}")
        # Count entries whose claimed start is non-negative and inside the body.
        good = sum(1 for s in starts if 0 <= s < len(body))
        print(f"   entries with an in-body start: {good} of {len(positions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
