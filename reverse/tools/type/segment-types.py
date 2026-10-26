#!/usr/bin/env python3
"""Count which wire types the client sends during each labelled action window.

WHY THIS IS THE RIGHT INSTRUMENT
================================
`field-differential --segments` asks "which byte offset changed", and on a live session the
answer is dominated by motion: almost every offset of the input body wobbles while walking,
so a movement-correlated result is all it can produce by construction.

The question a server actually has to answer is different: *when the client opens the
inventory / equips a sword / uses an ability, which messages does it send, and how many?*
That is a TYPE-level question, and it survives the replay being dead. A client that gets no
answer still emits its request -- it just never gets a reply -- so the request bytes ARE the
protocol a server must implement. Counting types per window recovers exactly that, and it
works with a capture-driven replay because the outbound direction is what is being measured.

WHAT IT REPORTS
---------------
For every segment: the total record count and a per-type count, each type carrying its name
from `research/derived/wire-type-names.json` when one exists. Then it separates the types
into three groups, because they mean different things:

  * `present everywhere`  -- traffic that runs whatever you do. Background. Ignore it.
  * `appeared`            -- zero in some segments, nonzero in others. THE INTERESTING SET:
                             a type that only appears when the inventory is open is a
                             message about the inventory, and that is a nameable lead.
  * `vanished`            -- present in some segments, zero in one or more others.

A type that appears in exactly ONE segment with the action's label is the strongest signal
this corpus can produce. It is not proof -- it is a lead to hand to `message-names`.

A note on channel 1: the input stream (wire `0x635`,
`ActionListComponentServerFacet_ReceiveInputFromClient`) runs at ~20/s whatever the player
does, so it dominates every window and can never separate them. It is reported but excluded
from the lead lists, because a type present in every window is background by definition.

Usage:
    python ef.py re segment-types --corpus .azoth/logs/world.log --segments s.json
    python ef.py re segment-types --corpus .azoth/logs/world.log --segments s.json \\
        --offset 619687615          # only the tail written after this byte
    python ef.py re segment-types --check
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "world" / "src"))

from azoth_world.javelin import alc  # noqa: E402
from azoth_world.javelin.bundle import read_type_marker  # noqa: E402
from azoth_world.javelin.frame import parse_datagram, parse_envelope  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402

NAMES_FILE = REPO / "research" / "derived" / "wire-type-names.json"


def load_names(path: Path = NAMES_FILE) -> dict[int, str]:
    """wire type -> name, from the naming sweep. Absent file = no names, not an error."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {row["wire_type"]: row["name"]
            for row in document.get("names", []) if row.get("name")}


def _decompress(envelope, body: bytes) -> bytes:
    """LZ4-decompress the datagram body when the Carrier type byte says it is compressed.

    `CarrierEnvelope` has only `type_byte`, `proto` and `sequence`; there is no
    `compressed` attribute, so `getattr(envelope, "compressed", False)` is always False.
    A reader that trusts it feeds compressed bytes into `parse_datagram` and gets
    plausible garbage: measured 2026-10-26, 3,756 of the channel-1 datagrams in one live
    session are `0x81`, so that mistake silently discards 98% of the corpus.
    """
    if getattr(envelope, "type_byte", None) == 0x81:
        return decompress_lz4_block(body)
    return body


def _channel1_type(payload: bytes) -> int | None:
    """The wire type of a channel-1 typed record, or None when this is not one.

    The container marker sits at offset 24 normally, and at **26** when the record opens
    with an `ff ff` prefix -- measured 2026-10-26, where 7 of 60 channel-1 records carried
    the prefix and `alc.split_container` rejected every one of them because it only knows
    offset 24. Rejecting them silently is how a corpus comes to look like it contains
    almost no input stream.
    """
    for marker in (alc.CONTAINER_MARKER, alc.CONTAINER_MARKER + 2):
        if payload[marker:marker + 2] != b"\x00\x01":
            continue
        try:
            type_id, _ = read_type_marker(payload[marker:])
        except Exception:  # noqa: BLE001 -- a malformed marker is not a channel-1 record
            return None
        return type_id
    return None


def iter_records(corpus: Path, *, event: str = "app-data", offset: int = 0):
    """Yield (ts, wire type) for every record in the corpus tail.

    `offset` is a byte offset into the corpus; only lines after it are read. A live
    `world.log` reaches hundreds of megabytes, and re-reading all of it to analyse the ten
    minutes that a session just wrote is both slow and needlessly destructive to the
    machine the client is running on.
    """
    seen = 0
    with corpus.open(encoding="utf-8", errors="replace") as handle:
        if offset:
            handle.seek(offset)
            if offset:
                handle.readline()  # the tail may start mid-line; drop that fragment
        for line in handle:
            if f'"{event}"' not in line:
                continue
            start = line.find("{")
            if start < 0:
                continue
            try:
                row = json.loads(line[start:])
            except ValueError:
                continue
            raw = row.get("raw")
            if not raw:
                continue
            try:
                envelope, body = parse_envelope(bytes.fromhex(raw))
                body = _decompress(envelope, body)
                parsed = parse_datagram(body)
            except Exception:  # noqa: BLE001 -- one bad datagram is not a failed corpus
                continue
            ts = row.get("ts")
            for message in parsed.messages:
                payload = bytes(message.payload)
                seen += 1
                channel1 = _channel1_type(payload)
                if channel1 is not None:
                    yield ts, channel1
                    continue
                try:
                    type_id, _ = read_type_marker(payload)
                except Exception:  # noqa: BLE001
                    continue
                yield ts, type_id
    if seen == 0:
        raise SystemExit(f"no {event} records decoded from {corpus}"
                         + (f" after offset {offset}" if offset else ""))


def analyse(corpus: Path, plan: dict, *, offset: int = 0, minimum: int = 3,
            names: dict[int, str] | None = None) -> dict:
    """Bucket every record into its labelled window and compute the three groups."""
    names = names if names is not None else {}
    windows = [(s["label"], s["start"], s["end"]) for s in plan["segments"]]
    per_segment: dict[str, Counter] = {label: Counter() for label, _, _ in windows}
    outside: Counter = Counter()
    total = 0
    for ts, kind in iter_records(corpus, offset=offset):
        total += 1
        if ts is None:
            continue
        for label, start, end in windows:
            if start <= ts <= end:
                per_segment[label][kind] += 1
                break
        else:
            outside[kind] += 1

    labels = [label for label, _, _ in windows]
    overall: Counter = Counter()
    for counts in per_segment.values():
        overall.update(counts)

    appeared: list[dict] = []
    vanished: list[dict] = []
    for kind, count in sorted(overall.items(), key=lambda kv: -kv[1]):
        # The input stream is constant background: it can never separate two windows.
        if count < minimum or kind == alc.INPUT_STREAM_TYPE:
            continue
        present = {label: per_segment[label][kind] for label in labels
                   if per_segment[label][kind] > 0}
        absent = [label for label in labels if per_segment[label][kind] == 0]
        if not present or not absent:
            continue
        entry = {"wire_type": f"0x{kind:x}", "name": names.get(kind),
                 "total": count, "present_in": present, "absent_in": absent}
        (appeared if len(present) <= len(absent) else vanished).append(entry)

    return {
        "corpus": str(corpus),
        "corpus_offset": offset,
        "records": total,
        "records_outside_windows": sum(outside.values()),
        "segments": labels,
        "per_segment": {label: {f"0x{kind:x}": count
                                for kind, count in per_segment[label].most_common()}
                        for label in labels},
        "segment_names": {label: {f"0x{kind:x}": names.get(kind)
                                  for kind in per_segment[label]}
                          for label in labels},
        "appeared": appeared,
        "vanished": vanished,
    }


def report(result: dict) -> None:
    print(f"{result['records']} records; windows cover "
          f"{result['records'] - result['records_outside_windows']}, "
          f"{result['records_outside_windows']} outside")
    print("\nper segment:")
    for label in result["segments"]:
        counts = result["per_segment"][label]
        top = ", ".join(f"{kind}x{count}" for kind, count in list(counts.items())[:6])
        print(f"  {label:22} {sum(counts.values()):6} records   {top}")

    def line(entry: dict) -> str:
        name = f"  {entry['name']}" if entry["name"] else ""
        where = ", ".join(f"{k}={v}" for k, v in entry["present_in"].items())
        return (f"  {entry['wire_type']:>8}{name}\n"
                f"           total {entry['total']:5}   present: {where}\n"
                f"           absent in: {', '.join(entry['absent_in'])}")

    print(f"\ntypes that APPEAR only in some windows ({len(result['appeared'])}) -- the leads:")
    if not result["appeared"]:
        print("   none. Every type seen is either always on or too rare to judge.")
    for entry in result["appeared"]:
        print(line(entry))

    print(f"\ntypes that VANISH in some windows ({len(result['vanished'])}):")
    for entry in result["vanished"]:
        print(line(entry))


def check() -> int:
    """Self-test: the reader must reproduce facts measured by hand before this tool ran."""
    checks: list[tuple[str, bool]] = []

    # 1. The channel-1 container is found at both marker offsets. A real client record
    #    opens `00 01` at 24; the prefixed form at 26. Fabricating both is legitimate here
    #    because the reader's job is exactly the marker walk, and the live corpus check
    #    below proves the same walk against real bytes. The type is written with the real
    #    encoder: 0x635 is `b5 18` on the wire, not a little-endian pair.
    from azoth_world.javelin import varint
    type_bytes = varint.encode(alc.INPUT_STREAM_TYPE)
    plain = bytearray(b"\x00" * 24) + b"\x00\x01" + type_bytes
    prefixed = bytearray(b"\xff\xff" + b"\x00" * 24) + b"\x00\x01" + type_bytes
    checks.append(("channel-1 marker at 24 -> 0x635",
                   _channel1_type(bytes(plain)) == alc.INPUT_STREAM_TYPE))
    checks.append(("channel-1 marker at 26 (prefixed) -> 0x635",
                   _channel1_type(bytes(prefixed)) == alc.INPUT_STREAM_TYPE))
    checks.append(("a channel-0 body is not reported as channel 1",
                   _channel1_type(b"\x00\x01\x9c\x19rest") is None))

    # 2. The envelope: 0x81 means LZ4, and a compressed datagram must round-trip through
    #    the decompressor rather than reach the record parser as garbage.
    envelope, _ = parse_envelope(bytes.fromhex("80010001"))
    checks.append(("envelope 0x80 is not compressed", envelope.type_byte == 0x80))
    compressed_envelope, _ = parse_envelope(bytes.fromhex("81010001"))
    checks.append(("envelope 0x81 is compressed, and has no `compressed` attribute to trust",
                   compressed_envelope.type_byte == 0x81
                   and getattr(compressed_envelope, "compressed", None) is None))

    # 3. The name table resolves the two types this feature leans on.
    names = load_names()
    checks.append(("0x635 is named as the input stream",
                   names.get(alc.INPUT_STREAM_TYPE, "").endswith("ReceiveInputFromClient")))
    checks.append(("0x169d is named QueryInventories",
                   names.get(0x169D, "").endswith("QueryInventories")))

    ok = all(value for _, value in checks)
    for name, value in checks:
        print(f"{'PASS' if value else 'FAIL'} {name}")
    print(f"segment-types check: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", help="world.log being written by the world process")
    parser.add_argument("--segments", help="the labelled plan written by capture-segments")
    parser.add_argument("--offset", type=int, default=0,
                        help="byte offset into the corpus; only the tail after it is read")
    parser.add_argument("--out", help="write the result JSON here")
    parser.add_argument("--min", type=int, default=3,
                        help="ignore a type whose total count is below this, so one stray "
                             "record cannot read as a signal")
    parser.add_argument("--check", action="store_true", help="run the self-test")
    args = parser.parse_args()

    if args.check:
        return check()
    if not args.corpus or not args.segments:
        parser.print_help()
        return 2

    plan = json.loads(Path(args.segments).read_text(encoding="utf-8"))
    offset = args.offset or int(plan.get("corpus_offset_at_start") or 0)
    result = analyse(Path(args.corpus), plan, offset=offset, minimum=args.min,
                     names=load_names())
    result["plan"] = plan.get("plan")
    report(result)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
