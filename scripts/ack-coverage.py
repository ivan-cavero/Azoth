#!/usr/bin/env python3
"""Decode the client's CT_ACKS coverage for the current session.

Question: how much of OUR outbound datagram stream has the client acked?
Prints per-session: last acked seq, bitmap coverage % of the replay window.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "world" / "src"))
from azoth_world.javelin import parse_datagram, parse_envelope  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

LOG = Path(__file__).resolve().parents[1] / "services" / "world" / "rep_traffic.jsonl"


def main() -> int:
    lines = LOG.read_text(encoding="utf-8").splitlines()
    start = 0
    for i, line in enumerate(lines):
        if '"event": "dtls-established"' in line:
            start = i
    acked: set[int] = set()
    our_last = 0
    for line in lines[start:]:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "app-data":
            try:
                data = bytes.fromhex(ev["raw_full"])
                env, body = parse_envelope(data)
                if env.is_compressed:
                    body = decompress_lz4_block(body)
                for rec in parse_datagram(body).messages:
                    if rec.is_system and rec.system_msg_id == 6 and len(rec.payload) >= 3:
                        p = rec.payload
                        flags = p[0]
                        last = int.from_bytes(p[1:3], "big")
                        acked.add(last)
                        if flags & 0x80:
                            n = min(flags & 0x7F, len(p) - 3)
                            for b in range(n):
                                for i in range(8):
                                    if p[3 + b] & (1 << i):
                                        s = last - 1 - (b * 8 + i)
                                        if s >= 0:
                                            acked.add(s)
                        elif flags & 0x40 and len(p) >= 5:
                            first = int.from_bytes(p[3:5], "big")
                            acked.update(range(first, last + 1))
            except Exception:  # noqa: BLE001
                continue
        elif ev.get("event") in ("reply", "keepalive"):
            raw = ev.get("raw", "")
            if len(raw) >= 8:
                try:
                    our_last = max(our_last, int(raw[4:8], 16))
                except ValueError:
                    pass
    lo, hi = 0, max(our_last, max(acked) if acked else 0)
    covered = sorted(s for s in acked if lo <= s <= hi)
    # coverage of contiguous prefix from 0
    contiguous = 0
    while contiguous in acked:
        contiguous += 1
    print(f"our outbound seqs up to: {our_last}")
    print(f"client acked: {len(acked)} seqs, max {max(acked) if acked else '-'}")
    print(f"contiguous acked prefix: 0..{contiguous - 1}")
    gaps = [s for s in range(0, min(our_last, 60)) if s not in acked]
    print(f"un-acked seqs in 0..{min(our_last, 60)}: {gaps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
