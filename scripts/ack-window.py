#!/usr/bin/env python3
"""Per-session ACK coverage for the replay burst.

`ack-coverage.py` answers "did the client ack our stream at all". This one
answers the question that matters for `connection_ingame_timeout`: for the
datagrams we actually sent during the last replay, which ones did the
client's CT_ACKS cover, and did the 46 KB world bundles (the ones the
client must reassemble to build entities) get acknowledged?

Run after a play session. Prints, per DTLS session:
  * our outbound envelope seq range and count
  * the acked set size / holes
  * for each replayed message, the datagram count it occupied and whether
    the client acked those datagrams.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "world" / "src"))

from azoth_world.javelin import parse_datagram, parse_envelope  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

LOG = ROOT / "services" / "world" / "rep_traffic.jsonl"


def acks_from(ev: dict, acked: set[int]) -> None:
    try:
        data = bytes.fromhex(ev["raw_full"])
    except (KeyError, ValueError):
        return
    try:
        env, body = parse_envelope(data)
    except Exception:  # noqa: BLE001
        return
    if env.is_compressed:
        try:
            body = decompress_lz4_block(body)
        except Exception:  # noqa: BLE001
            return
    try:
        records = parse_datagram(body).messages
    except Exception:  # noqa: BLE001
        return
    for rec in records:
        # system msg 6 == CT_ACKS (GridMate)
        if not (rec.is_system and rec.system_msg_id == 6) or len(rec.payload) < 3:
            continue
        p = rec.payload
        flags = p[0]
        last = int.from_bytes(p[1:3], "big")
        acked.add(last)
        if flags & 0x80:  # AHF_BITS: bitmap of the 127 seqs before `last`
            for b in range(min(flags & 0x7F, len(p) - 3)):
                for bit in range(8):
                    if p[3 + b] & (1 << bit):
                        s = last - 1 - (b * 8 + bit)
                        if s >= 0:
                            acked.add(s)
        elif flags & 0x40 and len(p) >= 5:  # CONTINUOUS: [first,last]
            first = int.from_bytes(p[3:5], "big")
            acked.update(range(first, last + 1))


def main() -> int:
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    sessions: list[list[dict]] = []
    current: list[dict] = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "dtls-established":
            if current:
                sessions.append(current)
            current = []
        current.append(ev)
    if current:
        sessions.append(current)
    if not sessions:
        print("no DTLS sessions in log")
        return 1

    sess = sessions[-1]
    print(f"last session: {len(sess)} events, {sess[0].get('ts')} .. {sess[-1].get('ts')}")

    ours: set[int] = set()
    for ev in sess:
        if ev.get("event") in ("replay", "resend", "keepalive", "reply"):
            raw = ev.get("raw", "")
            # `raw` is the message body, not the envelope, for replay events;
            # the envelope seq is only present on the wire-level records.
            if len(raw) >= 8:
                try:
                    ours.add(int(raw[4:8], 16))
                except ValueError:
                    pass

    acked: set[int] = set()
    for ev in sess:
        if ev.get("event") == "app-data":
            acks_from(ev, acked)

    print(f"wire seqs seen in raw fields: {len(ours)}")
    print(f"client-acked seqs:           {len(acked)}  (max {max(acked) if acked else '-'})")
    if ours:
        holes = sorted(ours - acked)
        print(f"our seqs not acked:          {len(holes)} -> {holes[:24]}")

    counts: dict[int, int] = defaultdict(int)
    for ev in sess:
        if ev.get("event") == "replay":
            counts[ev.get("chunks", 0)] += 1
    print("replay messages by chunk count:", dict(sorted(counts.items())))
    big = [ev for ev in sess if ev.get("event") == "replay" and ev.get("size", 0) > 14000]
    print(f"messages >14KB (chunked): {len(big)}")
    for ev in big[:6]:
        print(f"   seq={ev.get('seq')} size={ev.get('size')} chunks={ev.get('chunks')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
