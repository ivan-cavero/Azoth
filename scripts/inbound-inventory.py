"""Inventory of what the CLIENT asks our server for, from a captured world session.

WHY THIS EXISTS
===============
The question "does our server have everything the client expects?" had no measurable answer.
This tool produces one: it decodes every client->server record in a session log and lists, per
wire type, the NAME of the message and how many times the client sent it.

It exists because the answer was worse than expected. `services/world/src/azoth_world/rep.py`
parses inbound datagrams only to ACK them and to capture the channel-1 body; there is no
inbound typed-message dispatcher at all (`grep -c dispatch_inbound` -> 0). So every typed
request the client makes is acknowledged at the transport level and then ignored at the
application level, and nothing in the logs says so.

HOW IT DECODES
==============
`parse_envelope` on the logged `raw_full`, LZ4-decompress when the envelope is `0x81`, then
`parse_datagram`. Calling `parse_datagram` on the truncated `raw` field fails
(`payload truncated: need 2048 bits, have 896`), which is why this uses `raw_full`.

Names come from `research/derived/wire-type-names.json` (regenerate with
`reverse/tools/scan-wire-names.py`). A type with no name is reported as `?` rather than
guessed: several wire types are not Javelin-typed at all and belong to another registry.

Usage:
    python scripts/inbound-inventory.py .azoth/logs/world.log
    python scripts/inbound-inventory.py <log> --session last    # only the last session
    python scripts/inbound-inventory.py <log> --json out.json
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

NAMES = ROOT / "research" / "derived" / "wire-type-names.json"


def load_names() -> dict[int, str]:
    if not NAMES.is_file():
        return {}
    data = json.loads(NAMES.read_text(encoding="utf-8"))
    return {
        r["wire_type"]: r["name"] for r in data["names"] if r.get("name")
    }


def last_session(lines: list[str]) -> list[str]:
    starts = [i for i, l in enumerate(lines) if "listening-dtls" in l]
    return lines[starts[-1]:] if starts else lines


def decode(record) -> tuple[int | None, int]:
    """(wire_type, payload_offset) for a client record, or (None, 0).

    The client's own container is `[u32 BE crc32][u32 BE len][16-byte target][00 01][type]...`,
    so the typed marker sits at offset 24 in that form. The server's form has it at 0. Try both
    and take whichever parses, so a container change shows up as an unnamed record rather than
    as a crash.
    """
    payload = getattr(record, "payload", b"")
    for offset in (0, 24):
        try:
            type_id, _ = read_type_marker(payload[offset:])
        except Exception:
            continue
        return type_id, offset
    return None, 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", nargs="?", default=str(ROOT / ".azoth" / "logs" / "world.log"))
    ap.add_argument("--session", choices=["last", "all"], default="last")
    ap.add_argument("--json")
    args = ap.parse_args()

    names = load_names()
    lines = Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines()
    if args.session == "last":
        lines = last_session(lines)

    per_channel: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    by_type: collections.Counter = collections.Counter()
    per_channel_type: dict[tuple[int, int], int] = collections.Counter()
    parsed = failed = 0
    for line in lines:
        i = line.find("{")
        if i < 0:
            continue
        try:
            event = json.loads(line[i:])
        except json.JSONDecodeError:
            continue
        if event.get("event") != "app-data":
            continue
        raw = event.get("raw_full") or event.get("raw") or ""
        try:
            envelope, body = parse_envelope(bytes.fromhex(raw))
            if envelope.is_compressed:
                body = lz4.decompress_lz4_block(body)
            records = parse_datagram(body).messages
        except Exception:
            failed += 1
            continue
        parsed += 1
        for record in records:
            per_channel[record.channel][getattr(record, "size", 0)] += 1
            type_id, _ = decode(record)
            if type_id is None:
                continue
            by_type[type_id] += 1
            per_channel_type[(record.channel, type_id)] += 1

    print(f"session datagrams parsed {parsed}, unparsed {failed}")
    print(f"records by channel: "
          f"{ {ch: sum(c.values()) for ch, c in sorted(per_channel.items())} }")
    print()
    print(f"{'wire':>6} {'count':>7}  {'channels':<12} name")
    rows = []
    for type_id, count in by_type.most_common():
        chans = sorted(ch for (ch, t) in per_channel_type if t == type_id)
        name = names.get(type_id, "?")
        rows.append({"wire_type": type_id, "count": count, "channels": chans, "name": name})
        print(f"{type_id:6d} {count:7d}  {str(chans):<12} {name}")
    unnamed = [r for r in rows if r["name"] == "?"]
    print()
    print(f"{len(rows)} distinct client->server types, {len(unnamed)} of them unnamed")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
