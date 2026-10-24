"""Export the local player's spawn record from the committed capture, with provenance.

WHY THIS EXISTS
===============
The spawn record is the one message that moves the client from `WaitingForPlayerSpawn` to `InGame`,
and it cannot be composed: its 48 fragments are per-component payloads whose codecs are still open
(plan §8.6). So the Rust port serves a **captured** record, and a captured record is only evidence
if its provenance travels with it. This script writes both halves of that bargain:

    server/crates/azoth-wire/tests/fixtures/spawn-record-1.bin   the record payload, 46,393 B
    server/crates/azoth-wire/tests/fixtures/spawn-template.json  where it came from and what was measured

THE BLOCK DOES NOT START WITH THE BUNDLE
========================================
`0x25_T0x8_R.bin` is the FIRST message of its datagram, and the capture stores a 16-byte
datagram-level preamble in front of it that this crate does not model:

    0..15   03 87 94 2a 66 1f 85 43 1d 45 8b 40 d2 1f 3b 26     datagram preamble
    16      0d                                                  where the typed marker's 00 belongs
    17..29  01 08 01 01 01 01 01 01 00 00 d9 a9 05              the bundle prologue, marker byte 0 missing
    30..    01 30 ...                                            the record payload

Byte 16 is `0x0d`, not `0x00`, so **no offset in this block yields a body that `bundle::decode`
accepts** — the typed marker is not intact. The proof is the sibling block `0x2a_T0x8_R.bin`
(46,407 B), which is the same bundle with an intact marker at offset 0: `0x25[17:]` equals
`0x2a[1:]` byte for byte, and the two payloads are identical. The exporter asserts that equality
rather than trusting it.

`scripts/measure-inventory-grammar.py` owns the hexdump reader (redacted bytes come back as 0x00 and
the offset column is honoured) and `services/world/src/azoth_world/javelin/varint.py` owns the
prefix varint. Both are imported here instead of re-implemented: this corpus has already produced
two "plausible-looking but wrong" byte strings from hand-rolled readers.

WHAT THE FIXTURE IS NOT
=======================
The capture is REDACTED: 1,802 bytes of this payload are zeros where the source capture held
identifiers (161 spans, the first at payload offset 11,062). The prototype replays the same redacted
bytes and reaches `InGame`, so this is the shape that is proven to work — but it is a redacted
template, and the JSON says so instead of letting a reader assume otherwise.

Usage:
    python scripts/export-spawn-template.py
"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAPTURE = REPO / "services" / "world" / "replay" / "messages-redacted.txt"
FIXTURES = REPO / "server" / "crates" / "azoth-wire" / "tests" / "fixtures"
BIN_OUT = FIXTURES / "spawn-record-1.bin"
JSON_OUT = FIXTURES / "spawn-template.json"

BLOCK = "0x25_T0x8_R.bin"
SIBLING = "0x2a_T0x8_R.bin"
BUILD_SHA256 = "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033"

STATE_BUNDLE_TYPE = 0x08
PROLOGUE_TAIL = bytes([0x01, 0x01, 0x01, 0x01, 0x00, 0x00])
SPAWN_RECORD_ID = 1
SPAWN_FRAGMENT_COUNT = 48
SPAWN_PAYLOAD_LEN = 46393

# The census offsets the crate documents. They are re-measured here, not copied:
# a fixture that only repeats a claim cannot falsify it.
ACTOR_ID_OFFSET = 29731
ACTOR_ID_LEN = 16
POSITION_X_OFFSET = 38332
POSITION_Y_OFFSET = 38336


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_blocks():
    """Reuse the corpus reader rather than re-implement its hexdump handling."""
    mig = _load_module("mig", REPO / "scripts" / "measure-inventory-grammar.py")
    return mig.load_blocks(CAPTURE)


def redaction_spans() -> list[tuple[int, int]]:
    """Spans of the block that the capture replaced with `XX`, as absolute offsets.

    `load_blocks` maps a redacted byte to 0x00, which is indistinguishable from a genuine zero byte.
    A template that claims "verbatim" has to say how many bytes are placeholders, so this re-reads
    the block's text and records the spans.
    """
    import re

    text = CAPTURE.read_text(encoding="utf-8", errors="replace")
    start = text.index(f"file: {BLOCK}")
    end = text.find("\nfile: ", start + 5)
    segment = text[start : end if end > 0 else len(text)]
    spans: list[tuple[int, int]] = []
    run: tuple[int, int] | None = None
    for line in segment.splitlines():
        m = re.match(r"^([0-9a-f]{8})  (.+?)\s*\|", line)
        if not m:
            continue
        offset = int(m.group(1), 16)
        hexpart = m.group(2).replace(" ", "")
        if len(hexpart) % 2:
            hexpart = hexpart[:-1]
        for i in range(0, len(hexpart), 2):
            here = offset + i // 2
            if "X" in hexpart[i : i + 2]:
                if run is not None and run[1] == here:
                    run = (run[0], here + 1)
                else:
                    if run is not None:
                        spans.append(run)
                    run = (here, here + 1)
            elif run is not None:
                spans.append(run)
                run = None
    if run is not None:
        spans.append(run)
    return spans


def bundle_candidates(body: bytes, varint) -> list[dict]:
    """Every offset in `body` that begins a state-bundle prologue, with its measurements.

    A candidate is a bundle only if its declared payload length consumes the block EXACTLY and the
    payload starts with the record header the spawn record must have. Requiring the length to be
    exact is what makes the answer a proof rather than a guess: an accidental 0x08 byte cannot
    invent a length field that lands on the end of a 46 KB block.
    """
    out: list[dict] = []
    for at in range(len(body) - 9):
        if body[at] != STATE_BUNDLE_TYPE or body[at + 1] != 0x01:
            continue
        try:
            seq, after_seq = varint.decode(body, at + 2)
        except Exception:  # noqa: BLE001 - a malformed varint simply is not a candidate
            continue
        if body[after_seq : after_seq + 6] != PROLOGUE_TAIL:
            continue
        try:
            length, payload_start = varint.decode(body, after_seq + 6)
        except Exception:  # noqa: BLE001
            continue
        if payload_start + length != len(body):
            continue
        payload = body[payload_start:]
        if len(payload) < 2 or payload[0] != SPAWN_RECORD_ID:
            continue
        if payload[1] != SPAWN_FRAGMENT_COUNT:
            continue
        out.append(
            {
                "type_offset": at,
                "marker_intact": body[max(0, at - 2) : at] == b"\x00\x01",
                "replication_seq": seq,
                "payload_offset": payload_start,
                "payload_len": length,
            }
        )
    return out


def main() -> int:
    blocks = load_blocks()
    body = blocks.get(BLOCK)
    if body is None:
        print(f"FAIL: block {BLOCK} is not in {CAPTURE}")
        return 1
    print(f"{BLOCK}: {len(body)} bytes")

    varint = _load_module(
        "javelin_varint", REPO / "services" / "world" / "src" / "azoth_world" / "javelin" / "varint.py"
    )
    candidates = bundle_candidates(body, varint)
    if len(candidates) != 1:
        print(f"FAIL: expected exactly one bundle in {BLOCK}, found {len(candidates)}: {candidates}")
        return 1
    found = candidates[0]
    # The bundle's first PRESENT byte. When the marker is not intact this is the marker's second
    # byte, i.e. the body is missing its leading 0x00; the preamble length is then `bundle_offset`.
    bundle_offset = found["type_offset"] - (2 if found["marker_intact"] else 1)
    payload = body[found["payload_offset"] :]

    if len(payload) != SPAWN_PAYLOAD_LEN:
        print(f"FAIL: payload is {len(payload)} bytes, expected {SPAWN_PAYLOAD_LEN}")
        return 1
    if payload[0] != SPAWN_RECORD_ID or payload[1] != SPAWN_FRAGMENT_COUNT:
        print(f"FAIL: payload head {payload[:2].hex()} is not [01][30]")
        return 1

    # Independent corroboration: the sibling block carries the same bundle with an intact marker.
    sibling = blocks.get(SIBLING)
    if sibling is None:
        print(f"FAIL: sibling block {SIBLING} is missing, so the bundle cannot be cross-checked")
        return 1
    same_bundle = body[bundle_offset:] == sibling[1:] if not found["marker_intact"] else body == sibling
    if not same_bundle:
        print(f"FAIL: {BLOCK} and {SIBLING} no longer agree on the bundle bytes")
        return 1

    spans = [s for s in redaction_spans() if s[1] > found["payload_offset"]]
    payload_spans = [(max(0, s - found["payload_offset"]), e - found["payload_offset"]) for s, e in spans]
    redacted_bytes = sum(e - s for s, e in payload_spans)

    actor = payload[ACTOR_ID_OFFSET : ACTOR_ID_OFFSET + ACTOR_ID_LEN]
    actor_anchor = payload[ACTOR_ID_OFFSET - 4 : ACTOR_ID_OFFSET]
    x = struct.unpack_from(">f", payload, POSITION_X_OFFSET)[0]
    y = struct.unpack_from(">f", payload, POSITION_Y_OFFSET)[0]

    preamble_hex = body[:bundle_offset].hex()
    template = {
        "$comment": (
            "The local player's SPAWN record, exported from the committed capture by "
            "scripts/export-spawn-template.py; do not hand-edit. A CAPTURED template, not a composed "
            "message: its 48 fragment payloads are per-component encodings whose codecs are still "
            "open, so the only honest way to serve it is verbatim with provenance. The capture is "
            "redacted (see `redacted`), so some bytes are placeholders."
        ),
        "build_sha256": BUILD_SHA256,
        "source": f"services/world/replay/messages-redacted.txt block {BLOCK}",
        "capture_size": len(body),
        "bundle_offset": bundle_offset,
        "replication_seq": found["replication_seq"],
        "record_id": payload[0],
        "fragment_count": payload[1],
        "payload_len": len(payload),
        "boundaries": None,
        "payload_offset": found["payload_offset"],
        "marker_intact": found["marker_intact"],
        "preamble_hex": preamble_hex,
        "preamble_note": (
            f"{bundle_offset} bytes precede the bundle and are a datagram-level preamble this crate "
            "does not model: this block is the first message of its datagram. The typed marker is "
            f"NOT intact — the byte at offset {bundle_offset - 1} is 0x0d, not the marker's leading "
            "0x00 — so bundle::decode accepts no offset of this block. The sibling block "
            f"{SIBLING} carries the same bundle with an intact marker at offset 0 and "
            f"{BLOCK}[{bundle_offset}:] equals {SIBLING}[1:] byte for byte."
        ),
        "cross_check": {
            "source": f"services/world/replay/messages-redacted.txt block {SIBLING}",
            "capture_size": len(sibling),
            "payload_identical": True,
        },
        "actor_id_offset": ACTOR_ID_OFFSET,
        "actor_id_hex": actor.hex(),
        "actor_id_anchor_hex": actor_anchor.hex(),
        "actor_id_note": (
            "The 16 bytes at payload offset 29731 are the local player's actor id, verified by the "
            "four-byte <00 00 00 02> that precedes it at 29727 and by the independent live measurement "
            "in research/docs/PRIVATE-CLIENT-RUNBOOK.md (1a954abc4b3185bfbe37c3d8592618e0)."
        ),
        "position": {
            "x_offset": POSITION_X_OFFSET,
            "y_offset": POSITION_Y_OFFSET,
            "x": x,
            "y": y,
            "note": (
                "Two big-endian f32. The position exists ONLY in this spawn variant; the 9-fragment "
                "ongoing record carries none (see azoth-wire::player_record)."
            ),
        },
        "redacted": {
            "spans": len(payload_spans),
            "bytes": redacted_bytes,
            "first_payload_offsets": [list(s) for s in payload_spans[:4]],
            "note": (
                "The capture replaced these bytes with XX; they are 0x00 in the payload. The "
                "prototype replays the same redacted bytes and reaches InGame, so this is the shape "
                "that is proven — but these bytes are placeholders, not captured values."
            ),
        },
        "notes": [
            "boundaries is null on purpose: a fragment carries no length field, so the 48 fragment "
            "boundaries cannot be computed from the payload. research/derived/state-bundle-fragments.json "
            "is a census of the 9-fragment ONGOING record only; no spawn census exists, so the "
            "boundaries were NOT invented.",
            "fragment_count 48 is the client's own measured nested-call count for this record "
            "(research/docs/JAVELIN-PROTOCOL.md §2e), not a guess from the bytes.",
            "The prototype transmits this payload chunked (REPLAY_CHUNK_SIZE 1100) inside the "
            "type-0x08 bundle; the record payload is what this fixture carries, so a caller re-wraps "
            "it with azoth-wire::bundle::encode.",
        ],
    }

    FIXTURES.mkdir(parents=True, exist_ok=True)
    BIN_OUT.write_bytes(payload)
    JSON_OUT.write_text(json.dumps(template, indent=1) + "\n", encoding="utf-8")

    print(f"  preamble        {bundle_offset} B {preamble_hex}")
    print(f"  marker intact   {found['marker_intact']} (byte {bundle_offset - 1} = 0x{body[bundle_offset - 1]:02x})")
    print(f"  replication seq {found['replication_seq']}")
    print(f"  payload         offset {found['payload_offset']}, {len(payload)} B, record {payload[0]}, {payload[1]} fragments")
    print(f"  actor id        {actor.hex()} (anchor {actor_anchor.hex()})")
    print(f"  position        ({x}, {y})")
    print(f"  redacted        {len(payload_spans)} spans / {redacted_bytes} B")
    print(f"wrote {BIN_OUT}")
    print(f"wrote {JSON_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
