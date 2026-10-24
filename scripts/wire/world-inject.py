#!/usr/bin/env python3
"""Inject a raw post-V3 Carrier datagram into a LIVE world session.

Writes <repo>/services/world/inject.hex; the world server's PeerSession
picks it up on its next tick, sends it to the connected client, and
deletes the file. This avoids a game restart (the panel does not
re-render on re-poll) when probing message bodies.

Usage:
  python scripts/world-inject.py self-ident [--body-hex HEX] [--seq N]
  python scripts/world-inject.py level-info [--level NAME] [--seq N]
  python scripts/world-inject.py raw <datagram-hex>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "world" / "src"))

from azoth_world.javelin import (  # noqa: E402
    MessageRecord,
    marshal_datagram,
)

INJECT = ROOT / "services" / "world" / "inject.hex"


def _typed_record(type_header: bytes, body: bytes, seq: int, rel: int) -> MessageRecord:
    inner = type_header + body
    n = len(inner)
    if n < 128:
        vlq = bytes([n])
    else:
        out = bytearray()
        while n >= 0x80:
            out.append((n & 0x7F) | 0x80)
            n >>= 7
        out.append(n)
        vlq = bytes(out)
    return MessageRecord(
        channel=0,
        payload=vlq + inner,
        sequence=seq,
        reliable_sequence=rel,
        reliable=True,
        connecting=False,
        flags_override=0x21,
    )


def _datagram(records: list[MessageRecord], seq: int) -> bytes:
    return b"\x80\x01" + seq.to_bytes(2, "big") + marshal_datagram(records)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)

    p1 = sub.add_parser("self-ident")
    p1.add_argument("--body-hex", default=None)
    p1.add_argument("--seq", type=int, default=0x100)

    p2 = sub.add_parser("level-info")
    p2.add_argument("--level", default="NewWorld_VitaeEterna")
    p2.add_argument("--seq", type=int, default=0x101)

    p3 = sub.add_parser("raw")
    p3.add_argument("hex")

    args = ap.parse_args()

    if args.kind == "raw":
        data = bytes.fromhex(args.hex)
    elif args.kind == "self-ident":
        body = bytes.fromhex(args.body_hex) if args.body_hex else b""
        rec = _typed_record(bytes((0x00, 0x01, 0x91, 0x17)), body, 1, 1)
        data = _datagram([rec], args.seq)
    else:
        # LevelInfoChanged: 0x86 0x14 -> type id (0x86 & 0x7f) | (0x14 << 6)
        # = 0x06 | 0x500 = 0x506. Keep the header the world server used.
        name = args.level.encode()
        body = (
            len(name).to_bytes(4, "little") + name
            + (0).to_bytes(4, "little")            # other_name empty
            + (0).to_bytes(4, "little") * 4        # quad
            + (0).to_bytes(8, "little")            # field_60
            + (0).to_bytes(4, "little")            # extended count
            + bytes((0, 1, 1, 0))                  # flags
            + (1).to_bytes(8, "little")            # client_context_instance_id
        )
        rec = _typed_record(bytes((0x00, 0x01, 0x86, 0x14)), body, 1, 1)
        data = _datagram([rec], args.seq)

    INJECT.write_text(data.hex(), encoding="ascii")
    print(f"wrote {INJECT} ({len(data)} bytes): {data.hex()[:80]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())