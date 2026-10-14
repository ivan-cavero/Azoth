"""Audit the Carrier ACK stream and the client's retransmit factor in a world session.

WHY THIS EXISTS
===============
A measured session died of a client retransmit storm, and nothing in the repository could see
it. The client re-sent every reliable record ~200 times for the last 10 minutes while its log
said only `OnLocalNetworkConnectionWarning`, and the server logs looked healthy.

The mechanism, measured 2026-10-14: the server's CT_ACKS is a CONTINUOUS range
`[ack_first, ack_last]` encoded in two 16-bit fields. `ack_first` used to be pinned to the
session's first inbound sequence, so the range grew by one per datagram; once its width passed
half the space (32768) the range became ambiguous and the client stopped treating its records
as delivered. It did not error - it retransmitted. The onset was exact:

    32767 at 08:42:44 -> 32768 at 08:42:44 -> first retransmitted record at 08:42:45
    140 174 channel-0 records in 10 min carrying only 660 distinct sequences (212x)

This tool makes both halves measurable from a session log alone:
  * **ACK health** - the width of every CT_ACKS we sent, and whether it ever reaches 32768;
  * **client retransmits** - distinct sequences vs total records per type, so a storm is a
    number and not an impression.

Usage:
    python scripts/ack-audit.py .azoth/logs/world.log
    python scripts/ack-audit.py <log> --session last --check
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "world" / "src"))

from azoth_world.javelin import lz4  # noqa: E402
from azoth_world.javelin.bundle import read_type_marker  # noqa: E402
from azoth_world.rep import parse_datagram, parse_envelope  # noqa: E402

# Half the 16-bit sequence space: a continuous range this wide can no longer be told apart
# from its complement by a wrap-aware reader.
AMBIGUOUS_WIDTH = 0x8000


def last_session(lines: list[str]) -> list[str]:
    starts = [i for i, l in enumerate(lines) if "listening-dtls" in l]
    return lines[starts[-1]:] if starts else lines


def _events(lines: list[str]):
    for line in lines:
        i = line.find("{")
        if i < 0:
            continue
        try:
            yield json.loads(line[i:])
        except json.JSONDecodeError:
            continue


def scan(lines: list[str]) -> dict:
    """Collect ACK ranges (ours) and per-type retransmit factors (the client's)."""
    acks: list[tuple[str, int, int]] = []
    per_type: dict[int, list[int]] = collections.defaultdict(list)
    envelope: list[tuple[str, int]] = []

    for event in _events(lines):
        name = event.get("event")
        ts = event.get("ts", "")
        if name == "reply":
            raw = event.get("raw") or event.get("raw_full") or ""
            try:
                _, body = parse_envelope(bytes.fromhex(raw))
                records = parse_datagram(body).messages
            except Exception:
                continue
            for rec in records:
                payload = rec.payload
                if rec.channel == 3 and payload and payload[0] == 0x40 and len(payload) >= 5:
                    ack_last = int.from_bytes(payload[1:3], "big")
                    ack_first = int.from_bytes(payload[3:5], "big")
                    acks.append((ts, ack_first, ack_last))
        elif name == "app-data":
            env = event.get("envelope") or {}
            seq = env.get("seq")
            if seq is not None:
                envelope.append((ts, seq))
            raw = event.get("raw_full") or ""
            try:
                env2, body = parse_envelope(bytes.fromhex(raw))
                if env2.is_compressed:
                    body = lz4.decompress_lz4_block(body)
                records = parse_datagram(body).messages
            except Exception:
                continue
            for rec in records:
                if rec.channel != 0:
                    continue
                payload = rec.payload
                type_id = None
                for offset in (0, 24):
                    try:
                        type_id, _ = read_type_marker(payload[offset:])
                    except Exception:
                        continue
                    break
                if type_id is None:
                    continue
                seq = getattr(rec, "sequence", None)
                if seq is not None:
                    per_type[type_id].append(seq)

    envelope.sort()
    widths = [((last - first) & 0xFFFF, ts, first, last) for ts, first, last in acks]
    retransmit = {}
    for type_id, seqs in per_type.items():
        retransmit[type_id] = {
            "records": len(seqs),
            "distinct": len(set(seqs)),
            "factor": len(seqs) / max(1, len(set(seqs))),
            "first_seq": min(seqs),
            "last_seq": max(seqs),
        }
    crossing = next(((ts, s) for ts, s in envelope if s >= AMBIGUOUS_WIDTH), None)
    return {
        "acks": len(acks),
        "max_width": max((w[0] for w in widths), default=0),
        "widest": max(widths, default=None),
        "over_limit": [w for w in widths if w[0] >= AMBIGUOUS_WIDTH],
        "first_width_at_limit": next((w for w in widths if w[0] >= AMBIGUOUS_WIDTH), None),
        "envelope_max": max((s for _, s in envelope), default=0),
        "envelope_count": len(envelope),
        "ambiguous_crossing": crossing,
        "retransmit": retransmit,
    }


def report(stats: dict) -> int:
    print(f"CT_ACKS we sent            : {stats['acks']}")
    print(f"widest ACK range           : {stats['max_width']}"
          f"  (ambiguous at {AMBIGUOUS_WIDTH})")
    if stats["widest"]:
        _, ts, first, last = stats["widest"]
        print(f"  widest at                : {ts}  first={first} last={last}")
    print(f"ACKs at/over the limit     : {len(stats['over_limit'])}")
    if stats["first_width_at_limit"]:
        _, ts, first, last = stats["first_width_at_limit"]
        print(f"  first one at             : {ts}  first={first} last={last}")
    print(f"inbound datagrams          : {stats['envelope_count']}  "
          f"max envelope seq {stats['envelope_max']}")
    print(f"crossed {AMBIGUOUS_WIDTH} at          : {stats['ambiguous_crossing']}")
    print()
    print(f"{'wire':>6} {'records':>8} {'distinct':>9} {'factor':>7}  first..last")
    for type_id, r in sorted(stats["retransmit"].items(), key=lambda kv: -kv[1]["records"]):
        if r["records"] < 5:
            continue
        print(f"{type_id:6d} {r['records']:8d} {r['distinct']:9d} {r['factor']:6.1f}x  "
              f"{r['first_seq']}..{r['last_seq']}")

    problems: list[str] = []
    if stats["over_limit"]:
        problems.append(
            f"{len(stats['over_limit'])} CT_ACKS range(s) reached width {AMBIGUOUS_WIDTH}: "
            "the client cannot disambiguate them (this is the measured storm trigger)"
        )
    for type_id, r in stats["retransmit"].items():
        if r["records"] >= 50 and r["factor"] >= 10:
            problems.append(
                f"wire {type_id}: retransmit factor {r['factor']:.0f}x over {r['records']} "
                "records - a storm"
            )
    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("ACK stream healthy: every continuous range is narrower than half the 16-bit space "
          "and no client type shows a retransmit storm")
    return 0


def _self_check() -> int:
    """The auditor must flag the measured defect and pass the fixed stream."""
    from azoth_world.rep import ACK_WINDOW, ack_window_first

    failures = []

    # The measured pre-fix stream: first pinned at 2, last growing past 32768.
    pinned = [((last - 2) & 0xFFFF, "", 2, last) for last in (32767, 32768, 40000)]
    if not [w for w in pinned if w[0] >= AMBIGUOUS_WIDTH]:
        failures.append("the pre-fix pinned range was not flagged")

    # The fixed stream: same last values, windowed first.
    for count, last in ((32768, 32768), (40001, 40000), (65542, 5)):
        first = ack_window_first(last, count)
        width = (last - first) & 0xFFFF
        if width >= AMBIGUOUS_WIDTH:
            failures.append(f"fixed range is still ambiguous at last={last} (width {width})")
        if width > ACK_WINDOW:
            failures.append(f"fixed range exceeds ACK_WINDOW at last={last} (width {width})")

    if failures:
        print("ack-audit self-check FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"ack-audit self-check OK: notes the ambiguous range and keeps the fixed one under "
          f"ACK_WINDOW={ACK_WINDOW}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", nargs="?", default=str(ROOT / ".azoth" / "logs" / "world.log"))
    ap.add_argument("--session", choices=["last", "all"], default="last")
    ap.add_argument("--check", action="store_true", help="self-test, reads no log")
    args = ap.parse_args()

    if args.check:
        return _self_check()

    lines = Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines()
    if args.session == "last":
        lines = last_session(lines)
    return report(scan(lines))


if __name__ == "__main__":
    raise SystemExit(main())
