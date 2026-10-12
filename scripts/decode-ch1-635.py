#!/usr/bin/env python3
"""Decode the client's channel-1 local-player stream (wire type 0x635).

WHY. The client sends ONE message type on channel 1, about 20 times a second, and the
server has never answered on that channel. Wire type 0x635 (1589) is
GUID 01346CCD-785E-448D-A429-4B281972B1D7; it is not in the Javelin registry, so it is
the client's own local-player state/input stream. Its body was reported as "byte
identical across 3038 records", which is the single most important clue for movement:
if the client is streaming its state, the server can learn the player's position from
it and answer authoritatively; if the body never changes, the client is not simulating
anything and the stream is a keepalive.

This tool takes the raw Carrier records out of the world server's traffic log, keeps
only channel-1 typed records, strips the container
(`[u32 BE crc32][u32 BE len][16-byte target][00 01][prefix-varint type]`), and reports:

  * how many records there are, grouped by body length;
  * for each length, the set of byte offsets that EVER differ (so the invariant part is
    visible immediately);
  * a float/int interpretation of every 4-byte window, to spot a coordinate triple.

Usage:
  python scripts/decode-ch1-635.py [--log .azoth/logs/world.log] [--show 3]
"""

from __future__ import annotations

import argparse
import collections
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "world" / "src"))
from azoth_world.javelin import parse_datagram, parse_envelope  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402
from azoth_world.javelin.varint import decode as varint_decode  # noqa: E402

TYPE_635 = 0x635


def records(path: Path):
    seen: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("[rep] "):
                line = line[6:]
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") != "app-data":
                continue
            raw = ev.get("raw_full")
            if not raw or raw in seen:
                continue
            seen.add(raw)
            try:
                env, body = parse_envelope(bytes.fromhex(raw))
                if env.is_compressed:
                    body = decompress_lz4_block(body)
                res = parse_datagram(body)
            except Exception:  # noqa: BLE001
                continue
            for rec in res.messages:
                if rec.channel != 1:
                    continue
                payload = rec.payload
                if len(payload) < 20 or payload[16:18] != b"\x00\x01":
                    continue
                try:
                    t, n = varint_decode(payload, 18)
                except Exception:  # noqa: BLE001
                    continue
                if t == TYPE_635:
                    yield payload[18 + n:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(ROOT / ".azoth" / "logs" / "world.log"))
    ap.add_argument("--show", type=int, default=3)
    args = ap.parse_args()

    bodies = list(records(Path(args.log)))
    if not bodies:
        print("no channel-1 type 0x635 records found")
        return 1

    by_len: dict[int, list[bytes]] = collections.defaultdict(list)
    for b in bodies:
        by_len[len(b)].append(b)
    print(f"records: {len(bodies)}  distinct body lengths: {sorted(by_len)}")
    print()

    for length, group in sorted(by_len.items(), key=lambda kv: -len(kv[1])):
        if len(group) < 3:
            continue
        print(f"=== body length {length}: {len(group)} records")
        # offsets that differ
        varying = sorted({i for i in range(length) if len({g[i] for g in group}) > 1})
        print(f"    varying offsets ({len(varying)}): {varying}")
        first = group[0]
        print(f"    first: {first.hex()}")
        # 4-byte window interpretation
        print("    windows: off  u32        i32         f32")
        for off in range(0, length - 3, 4):
            raw = first[off:off + 4]
            u = struct.unpack("<I", raw)[0]
            i = struct.unpack("<i", raw)[0]
            f = struct.unpack("<f", raw)[0]
            flag = ""
            if abs(f) > 1.0 and 1e-6 < abs(f) < 1e9 and f == f:
                flag = "  <-- float-like"
            if any(abs(struct.unpack("<f", g[off:off + 4])[0] - f) > 1e-6
                   for g in group[:50]):
                flag += " (varies)"
            print(f"      {off:#04x} {u:10d} {i:11d} {f:12.5g}{flag}")
        for extra in group[1:args.show]:
            print(f"    next: {extra.hex()}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
