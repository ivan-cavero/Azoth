#!/usr/bin/env python3
"""Decode the client's ch0 1115B/161B blobs from the latest session.

Ground truth question: what does the client ask with the chunked 0x5
records during WaitingForPlayerSpawn/InGame?
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "world" / "src"))
from azoth_world.javelin import parse_datagram, parse_envelope  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

LOG = Path(__file__).resolve().parents[2] / "services" / "world" / "rep_traffic.jsonl"


def main() -> int:
    seen = set()
    shown = 0
    for line in reversed(LOG.read_text(encoding="utf-8").splitlines()):
        if '"channel": 0, "flags": "0x5"' not in line and '"channel": 0, "flags": "0x1"' not in line:
            continue
        m = re.search(r'"raw_full": "([0-9a-f]+)"', line)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        data = bytes.fromhex(m.group(1))
        try:
            env, body = parse_envelope(data)
            if env.is_compressed:
                body = decompress_lz4_block(body)
            result = parse_datagram(body)
        except Exception as exc:  # noqa: BLE001
            print("parse error:", exc)
            continue
        for rec in result.messages:
            if rec.channel != 0:
                continue
            print(
                f"flags={rec.flags:#x} size={rec.size} seq={rec.sequence} "
                f"rel={rec.reliable_sequence} chunks={rec.num_chunks}"
            )
            print("  payload[:64]:", rec.payload[:64].hex())
            shown += 1
        if shown >= 6:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
