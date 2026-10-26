#!/usr/bin/env python3
"""Find field boundaries in a wire type by differential analysis of many bodies.

WHY THIS EXISTS
===============
`research/atlas/meanings.md` records the gap plainly: 6 of 185 wire types are laid out
to the byte. The other 179 are named but not readable, so a server cannot compose them.
The atlas also records why naming does not close that gap -- a field NAME is not a field
ENCODING, and each field goes through its own codec.

This is the other route: measure encodings instead of reading code. Take many bodies of
ONE type, align them byte by byte, and ask which offsets never change and which do. A
region that is constant across every sample is not a field value -- it is a tag, a
reserved byte, or a length. A region that varies is carrying something. Boundaries then
fall out of where variability starts and stops.

WHAT IT CAN AND CANNOT DO
=========================
It finds CANDIDATE boundaries. It does not name fields and it does not prove a boundary:
a constant run inside a field's value is indistinguishable from two constant fields
without a sample that changes the value. That is why `--correlate` exists -- the only
thing that turns a boundary into a field is tying a byte range to an independently known
quantity.

Measured 2026-10-26 and worth knowing before pointing this at a corpus: the captured
replay is useless for this. Its state records are byte-identical by construction (24
copies of the spawn record, 5 of the player record), so every offset looks constant. The
variation in a live session lives in the CLIENT'S INPUT STREAM -- `0x635` alone gave
220,252 distinct bodies out of 220,367 in one session. Point this tool at a corpus that
actually varies or it will report a table of constants and look broken.

Usage:
    python ef.py run field-differential --type 0x635 --corpus <log>
    python ef.py run field-differential --type 0x635 --corpus <log> --min-samples 200
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "world" / "src"))

from azoth_world.javelin import alc, varint  # noqa: E402
from azoth_world.javelin.bundle import read_type_marker  # noqa: E402
from azoth_world.javelin.frame import parse_datagram, parse_envelope  # noqa: E402
from azoth_world.javelin.lz4 import decompress_lz4_block  # noqa: E402


def _decompress(envelope, body: bytes) -> bytes:
    """LZ4-decompress the datagram body when the Carrier type byte says it is compressed.

    `CarrierEnvelope` has only `type_byte`, `proto` and `sequence` -- there is **no**
    `compressed` attribute, so `getattr(envelope, "compressed", False)` is always False.
    This tool used to do exactly that and therefore fed compressed bytes straight into
    `parse_datagram`, which produced plausible-looking garbage: 3,802 records on channel 3
    and 60 on channel 1 out of 3,810 datagrams. Measured 2026-10-26: 3,756 of the
    channel-1 datagrams in one live session are `0x81`, so this quietly discarded 98% of
    the corpus while looking like it worked.
    """
    if getattr(envelope, "type_byte", None) == 0x81:
        return decompress_lz4_block(body)
    return body


def _channel1_body(payload: bytes) -> bytes | None:
    """Body of a channel-1 typed record, or None if this is not one.

    The container marker sits at offset 24 normally, and at **26** when the record opens
    with an `ff ff` prefix -- measured 2026-10-26 on a live movement session, where 7 of
    60 channel-1 records carried the prefix and `alc.split_container` rejected every one
    of them because it only knows offset 24. That rejection is silent at the call site:
    the caller catches the error, counts a non-match, and reports a corpus that appears
    to contain almost no input stream. It contained the grown bodies all along.
    """
    for marker in (alc.CONTAINER_MARKER, alc.CONTAINER_MARKER + 2):
        if payload[marker : marker + 2] != b"\x00\x01":
            continue
        try:
            type_id, body_offset = varint.decode(payload, marker + 2)
        except Exception:
            return None
        if type_id == alc.INPUT_STREAM_TYPE:
            return payload[body_offset:]
        return None
    return None


def iter_bodies(corpus: Path, want: int, *, event: str = "app-data"):
    """Yield body bytes for every message of `want` found in a world-log corpus.

    Two container shapes are handled because the client uses both: channel-0 records
    start with the `00 01` typed marker and their type is a prefix varint, while
    channel-1 records carry the type inside a container whose marker moves by two bytes
    when the record is prefixed. Guessing one shape and skipping the other is how a tool
    silently returns nothing.
    """
    seen = 0
    with corpus.open(encoding="utf-8", errors="replace") as handle:
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
            except Exception:
                continue
            for message in parsed.messages:
                payload = bytes(message.payload)
                seen += 1
                channel1 = _channel1_body(payload)
                if channel1 is not None:
                    if want == alc.INPUT_STREAM_TYPE:
                        yield channel1
                    continue
                # channel 0: the typed-stream marker
                try:
                    type_id, offset = read_type_marker(payload)
                except Exception:
                    continue
                if type_id == want:
                    yield payload[offset:]
    if seen == 0:
        raise SystemExit(f"no {event} records decoded from {corpus}")


def variability(bodies: list[bytes]) -> dict:
    """Per-offset constant/varying map over a set of bodies.

    Bodies are NOT zero-padded to a common length: a shorter body means the field that
    ends it was absent, so padding would invent bytes that are not on the wire. Offsets
    past a body's end are counted separately, which is itself a signal (a body that
    grows is a body whose tail fields appeared).
    """
    longest = max(len(b) for b in bodies)
    columns: list[Counter] = [Counter() for _ in range(longest)]
    absent = [0] * longest
    for body in bodies:
        for index in range(longest):
            if index < len(body):
                columns[index][body[index]] += 1
            else:
                absent[index] += 1
    rows = []
    for index, counter in enumerate(columns):
        distinct = len(counter)
        rows.append(
            {
                "off": index,
                "distinct": distinct,
                "varies": distinct > 1,
                "absent": absent[index],
                "top": [[value, count] for value, count in counter.most_common(4)],
            }
        )
    return {"lengths": sorted({len(b) for b in bodies}), "columns": rows}


def regions(rows: list[dict], min_run: int = 1) -> list[tuple[int, int, bool]]:
    """Collapse the per-offset map into (start, end, varies) runs.

    A run ends where the variability changes, which is the only boundary information this
    tool actually has. Reporting it as runs rather than as offsets keeps the output
    readable for a 200-byte body and makes an obviously wrong result (one huge constant
    run) visible at a glance.
    """
    if not rows:
        return []
    out: list[list] = []
    start = rows[0]["off"]
    current = rows[0]["varies"]
    for row in rows[1:]:
        if row["varies"] != current:
            out.append([start, row["off"] - 1, current])
            start, current = row["off"], row["varies"]
    out.append([start, rows[-1]["off"], current])
    return [(a, b, v) for a, b, v in out if (b - a + 1) >= min_run]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, help="wire type, e.g. 0x635")
    parser.add_argument("--corpus", required=True, help="world log to read")
    parser.add_argument("--min-samples", type=int, default=50,
                        help="refuse to report below this many bodies")
    parser.add_argument("--max-samples", type=int, default=20000,
                        help="cap so a huge corpus stays fast; distinctness is sampled")
    parser.add_argument("--length", type=int,
                        help="only analyse bodies of exactly this many bytes. REQUIRED in "
                             "practice: bodies of different lengths pad the comparison with "
                             "offsets that are 'absent' in most samples, which reads as "
                             "variation and drowns the real structure. Group by length first.")
    parser.add_argument("--out", help="write the full JSON map here")
    args = parser.parse_args()

    want = int(args.type, 16) if args.type.lower().startswith("0x") else int(args.type)
    corpus = Path(args.corpus)

    bodies: list[bytes] = []
    for body in iter_bodies(corpus, want):
        bodies.append(body)
        if len(bodies) >= args.max_samples:
            break

    if len(bodies) < args.min_samples:
        raise SystemExit(
            f"only {len(bodies)} bodies of type 0x{want:x} found (need {args.min_samples}). "
            "Differential analysis needs a corpus that varies; see this file's docstring."
        )

    if args.length is not None:
        before = len(bodies)
        bodies = [b for b in bodies if len(b) == args.length]
        if not bodies:
            raise SystemExit(
                f"no bodies of exactly {args.length} bytes (had {before} bodies of other lengths)"
            )
        print(f"filtered to {args.length} bytes: {len(bodies)} of {before} bodies")

    distinct = len(set(bodies))
    report = variability(bodies)
    runs = regions(report["columns"])

    print(f"type 0x{want:x}: {len(bodies)} bodies, {distinct} distinct, "
          f"lengths {report['lengths']}")
    if distinct < 2:
        print("\nALL BODIES IDENTICAL. There is nothing to differentiate: this corpus "
              "carries one value per offset, which is what a replayed capture looks like.")
        return 0

    constant = sum(len(r) for a, b, v in runs if not v for r in [range(a, b + 1)])
    varying = sum(len(r) for a, b, v in runs if v for r in [range(a, b + 1)])
    print(f"offsets: {constant} constant, {varying} varying\n")

    print("runs (start..end, varies?):")
    for start, end, varies in runs:
        width = end - start + 1
        flag = "VARIES" if varies else "const "
        sample = ""
        if varies:
            top = report["columns"][start]["top"]
            sample = "  e.g. " + ", ".join(f"0x{v:02x}x{c}" for v, c in top[:3])
        print(f"  0x{start:03x}..0x{end:03x}  {width:3}d  {flag}{sample}")

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(
                {"type": f"0x{want:x}", "bodies": len(bodies), "distinct": distinct,
                 "runs": runs, **report},
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
