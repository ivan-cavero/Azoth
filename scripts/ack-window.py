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

import argparse
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
    parser = argparse.ArgumentParser(description="Summarize Carrier ACKs for a REP session")
    parser.add_argument(
        "--session",
        type=int,
        default=-1,
        help="session index (0-based; negative indexes from the newest; default: -1)",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="list DTLS session boundaries without decoding payloads",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum session rows for --list-sessions; 0 lists all",
    )
    args = parser.parse_args()
    if not LOG.is_file():
        print(f"traffic log not found: {LOG}")
        return 1

    # The world log can be hundreds of MB. Find the last session boundary in a
    # bounded-memory pass, then parse only that session instead of read_text()
    # + splitlines() on the entire append-only capture.
    sessions: list[tuple[int, str, str]] = []
    with LOG.open("rb") as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if b'"event": "dtls-established"' in line:
                try:
                    event = json.loads(line)
                except (UnicodeDecodeError, ValueError):
                    event = {}
                sessions.append(
                    (offset, event.get("ts", ""), event.get("peer", ""))
                )
        if not sessions:
            print("no DTLS sessions in log")
            return 1
        if args.list_sessions:
            start = max(0, len(sessions) - args.limit) if args.limit > 0 else 0
            if start:
                print(f"showing sessions {start}..{len(sessions) - 1} of {len(sessions)}")
            for index, (_, ts, peer) in enumerate(sessions[start:], start=start):
                print(f"{index}: {ts} peer={peer}")
            return 0
        if not -len(sessions) <= args.session < len(sessions):
            print(f"session index out of range; log has {len(sessions)} sessions")
            return 2
        selected = args.session % len(sessions)
        session_start, session_ts, session_peer = sessions[selected]
        stream.seek(session_start)

        acked: set[int] = set()
        ours: set[int] = set()
        counts: dict[int, int] = defaultdict(int)
        chunks_by_replay: dict[int, list[tuple[int, int]]] = defaultdict(list)
        big: list[dict] = []
        event_count = 0
        first_ts = ""
        last_ts = ""
        started = False
        for line in stream:
            if b'"event": "dtls-established"' in line:
                if started:
                    break
                started = True
            try:
                ev = json.loads(line)
            except (UnicodeDecodeError, ValueError):
                continue
            event_count += 1
            first_ts = first_ts or ev.get("ts", "")
            last_ts = ev.get("ts", last_ts)
            event = ev.get("event")
            if event == "app-data":
                acks_from(ev, acked)
            elif event == "replay-chunk":
                try:
                    replay_seq = int(ev["replay_seq"])
                    chunk_index = int(ev["chunk_index"])
                    carrier_seq = int(ev["carrier_seq"])
                except (KeyError, TypeError, ValueError):
                    continue
                chunks_by_replay[replay_seq].append((chunk_index, carrier_seq))
                ours.add(carrier_seq)
            elif event == "replay":
                counts[ev.get("chunks", 0)] += 1
                if ev.get("size", 0) > 14000 and len(big) < 6:
                    big.append(ev)
            elif event == "resend":
                try:
                    ours.add(int(ev["seq"]) & 0xFFFF)
                except (KeyError, TypeError, ValueError):
                    pass

    if not event_count:
        print("no DTLS sessions in log")
        return 1
    print(
        f"session {selected}: {event_count} events, peer={session_peer}, "
        f"{session_ts or first_ts} .. {last_ts}"
    )
    print(f"tracked outbound Carrier seqs: {len(ours)}")
    print(f"client-acked seqs:           {len(acked)}  (max {max(acked) if acked else '-'})")
    if ours:
        holes = sorted(ours - acked)
        print(f"our seqs not acked:          {len(holes)} -> {holes[:24]}")

    print("replay messages by chunk count:", dict(sorted(counts.items())))
    if chunks_by_replay:
        print("per-message chunk ACK coverage:")
        for replay_seq, chunks in sorted(chunks_by_replay.items()):
            chunks.sort()
            missing = [(idx, carrier) for idx, carrier in chunks if carrier not in acked]
            acknowledged = len(chunks) - len(missing)
            missing_text = ", ".join(
                f"chunk {idx} (carrier {carrier})" for idx, carrier in missing
            ) or "none"
            print(
                f"   replay 0x{replay_seq:x}: {acknowledged}/{len(chunks)} ACKed; "
                f"missing: {missing_text}"
            )
    elif counts:
        print(
            "per-message ACK coverage unavailable: this capture predates "
            "replay-chunk records; tracked seqs are retransmissions only"
        )
    print(f"messages >14KB (chunked): {len(big)}")
    for ev in big[:6]:
        print(f"   seq={ev.get('seq')} size={ev.get('size')} chunks={ev.get('chunks')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
