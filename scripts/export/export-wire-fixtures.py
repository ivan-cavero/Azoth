"""Export wire fixtures from a world.log, for the Python-vs-Rust parity harness.

WHY THIS EXISTS
===============
"Byte-for-byte parity with the Python encoders" is only a claim until something
compares them. This extracts real datagrams from a live 1.460 session — the
envelope, the record framing, the channel-1 containers, and the state bundles —
into a compact JSON fixture file that both implementations read.

The fixtures are derived from a capture that is gitignored, so the output is
small and self-contained: the harness must run on a fresh checkout.

Usage:
    python scripts/export-wire-fixtures.py .azoth/logs/world.log \
        --out server/crates/azoth-wire/tests/fixtures/wire-fixtures.json \
        --limit 400
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from logwire import decode_input, iter_events, split_records  # noqa: E402

# The type-0x08 state bundle marker inside a server record's payload.
STATE_BUNDLE_MARKER = b"\x00\x01\x08"


def main() -> int:
    root = Path(__file__).resolve()
    while not (root / "ef.py").is_file() and root.parent != root:
        root = root.parent
    if not (root / "server" / "Cargo.toml").is_file():
        print("server/ is not in this checkout.")
        print("This helper used to write Rust fixtures. It does not recreate server/.")
        print("See research/atlas/meanings.md.")
        return 2
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", default="services/world/replay/messages-redacted.txt",
                    help="the committed replay dump, source of the server->client bundles")
    ap.add_argument("--limit", type=int, default=400,
                    help="maximum datagrams to keep per shape")
    ap.add_argument("--state-limit", type=int, default=200,
                    help="maximum state bundles to keep")
    ap.add_argument("--state-max-bytes", type=int, default=9000,
                    help="skip bundles larger than this: a 46 KB spawn record proves "
                         "nothing extra about the grammar and would bloat the fixture")
    args = ap.parse_args()

    datagrams: list[dict] = []
    channel1: list[dict] = []
    bundles: list[dict] = []
    skipped_large: list[int] = []
    seen_datagram_shapes: set[str] = set()

    for ev in iter_events(Path(args.log)):
        name = ev.get("event")
        if name == "app-data":
            raw = ev.get("raw")
            if not raw or len(datagrams) >= args.limit:
                continue
            try:
                datagram = bytes.fromhex(raw)
            except ValueError:
                continue
            records = split_records(datagram)
            if not records:
                continue
            # Keep a diverse set: one sample per (channel, payload-size) shape,
            # so the fixture covers every framing form rather than 400 copies of
            # the most common one.
            shape = "|".join(f"{ch}:{len(pl)}" for ch, pl in records)
            if shape in seen_datagram_shapes:
                continue
            seen_datagram_shapes.add(shape)
            datagrams.append({
                "raw": datagram.hex(),
                "shape": shape,
                "records": [{"channel": ch, "payload": pl.hex()} for ch, pl in records],
            })
            for ch, pl in records:
                if ch != 1:
                    continue
                d = decode_input(pl)
                if d is not None and len(channel1) < args.limit:
                    yaw, pitch, x, y, body, idx, _tgt = d
                    channel1.append({
                        "payload": pl.hex(),
                        "yaw": yaw,
                        "pitch": pitch,
                        "x": x,
                        "y": y,
                        "marker_offset": idx,
                        "body_length": len(body),
                    })
        elif name == "replay" and len(bundles) < args.state_limit:
            # The replay event carries the message size and type, not the bytes;
            # the bundle bodies come from the app-data path below.
            continue

    # State bundles: scan every inbound datagram's channel-0 payloads for the
    # 0x08 marker. These are the server's own records, so they exercise the
    # bundle grammar rather than the client's input stream.
    for ev in iter_events(Path(args.log)):
        if ev.get("event") != "app-data" or len(bundles) >= args.state_limit:
            continue
        raw = ev.get("raw")
        if not raw:
            continue
        try:
            datagram = bytes.fromhex(raw)
        except ValueError:
            continue
        for ch, pl in split_records(datagram):
            if ch != 0:
                continue
            pos = pl.find(STATE_BUNDLE_MARKER)
            if pos < 0:
                continue
            candidate = pl[pos:]
            bundles.append({"body": candidate.hex(), "length": len(candidate)})
            if len(bundles) >= args.state_limit:
                break

    # State bundles: the server->client direction does not appear in world.log
    # (that logs what the CLIENT sent), so they come from the committed replay
    # dump. 79 of its 177 blocks are type 0x08, which is the bundle corpus.
    corpus_path = Path(args.corpus)
    if corpus_path.is_file():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mig", Path(__file__).resolve().parents[1] / "measure" / "measure-inventory-grammar.py")
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        blocks = mig.load_blocks(corpus_path)
        for name, data in blocks.items():
            if len(bundles) >= args.state_limit:
                break
            if "T0x8_R" not in name or not data:
                continue
            # The dump's block begins at the record payload; find the typed marker
            # so the fixture starts exactly where the bundle grammar does.
            pos = data.find(STATE_BUNDLE_MARKER)
            if pos < 0:
                continue
            candidate = data[pos:]
            if len(candidate) > args.state_max_bytes:
                skipped_large.append(len(candidate))
                continue
            bundles.append({
                "body": candidate.hex(),
                "length": len(candidate),
                "source": name,
            })
    else:
        print(f"warning: corpus not found at {corpus_path}; no state bundles", file=sys.stderr)

    out = {
        "$comment": (
            "Wire fixtures exported from a live 1.460 session. Every entry is a "
            "real byte sequence the client sent or accepted; the parity harness "
            "requires the Python and Rust implementations to agree on all of them."
        ),
        "build_sha256": "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033",
        "source": str(args.log).replace("\\", "/"),
        "datagrams": datagrams,
        "channel1": channel1,
        "state_bundles": bundles,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    size = out_path.stat().st_size
    print(f"wrote {out_path}")
    print(f"  datagrams:      {len(datagrams)}")
    print(f"  channel-1:      {len(channel1)}")
    print(f"  state bundles:  {len(bundles)}")
    if skipped_large:
        print(f"  skipped large:  {len(skipped_large)} "
              f"({min(skipped_large)}..{max(skipped_large)} B)")
    print(f"  size:           {size / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
