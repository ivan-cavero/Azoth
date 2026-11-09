"""Capture what the Python reference would send for the ladder's inputs.

Drives the reference's own code (`javelin.frame.marshal_datagram` and its
`MessageRecord`/`MarshalState` writer, `javelin.wire.chunk_replay_payload`,
`encode_vlq32`, `rep.py::heartbeat_body`, and the `clock_sync_datagram`
keepalive's record shape) over the SAME six bodies the Rust ladder is built from,
in the capture's own order and the reference's tick order
(`PeerSession.tick`: `maybe_keepalive` before `maybe_pump_replay`, then
`maybe_heartbeat`'s record shape): keepalive, the `0x15d` ping, `0x40a`,
`0x1be`, the `0x65c` self-identification record, `0x663` level info, and the
`0x08` state bundle. The ping is printed on its own line because it REPEATS (the
reference re-sends it every second), so it is not one of the plan's records.

No Python file is modified. Read-only import of the oracle.

Prints the compact expectation table `tests/oracle_differential.rs` pins, so a
reviewer can regenerate it and check the table by eye. It writes nothing; the
scratch copy used during the investigation also dumped `oracle.json` for the
field-by-field diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "services" / "world" / "src" / "azoth_world").is_dir():
            return candidate
    raise SystemExit("run this from inside the Everfall repository")


REPO = _repo_root()
sys.path.insert(0, str(REPO / "services" / "world" / "src"))

from azoth_world.javelin.frame import MessageRecord, marshal_datagram  # noqa: E402
from azoth_world.javelin.varint import encode as varint_encode  # noqa: E402
from azoth_world.javelin.wire import chunk_replay_payload, encode_vlq32  # noqa: E402
from azoth_world.rep import heartbeat_body  # noqa: E402

REPLAY_CHUNK_SIZE = 1100
REPLAY_SINGLE_LIMIT = 256
REPLAY_CHUNK_COUNT_TOTAL = True
KEEPALIVE_MS = 1000


def fnv1a64(data: bytes) -> int:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


def wire_body(wire_id: int) -> bytes:
    text = json.loads((REPO / "research/fixtures/wire/wire-bodies.json").read_text())
    for record in text["records"]:
        if record["wire_id"] == wire_id:
            return bytes.fromhex(record["body"])
    raise SystemExit(f"no wire body {wire_id:#x}")


def state_bundle_body(name: str) -> bytes:
    doc = json.loads((REPO / "research/fixtures/wire/wire-fixtures.json").read_text())
    for bundle in doc["state_bundles"]:
        if bundle["source"] == name:
            return bytes.fromhex(bundle["body"])
    raise SystemExit(f"no state bundle {name}")


def typed_body(wire_id: int, card: bytes) -> bytes:
    return b"\x00\x01" + varint_encode(wire_id) + card


class Out:
    """The reference's `next_out_seq` / `out_msg_seq` / `out_rel_seq`."""

    def __init__(self, envelope: int) -> None:
        self.envelope = envelope & 0xFFFF
        self.message = 1  # _arm_replay sets out_msg_seq = 1
        self.reliable = 1

    def take_envelope(self) -> int:
        value = self.envelope
        self.envelope = (value + 1) & 0xFFFF
        return value


def keepalive(out: Out, clock: int, frames: list[dict]) -> None:
    """`rep.py::clock_sync_datagram` + `_send_datagram`."""
    rec = MessageRecord(
        channel=3,
        payload=(clock & 0xFFFFFFFF).to_bytes(4, "big") + bytes([4]),
        sequence=0,
        reliable_sequence=0xFFFF,
        reliable=False,
        connecting=False,
        flags_override=0x20,
    )
    carrier = out.take_envelope()
    frames.append(
        {
            "envelope": carrier,
            "chunk_index": None,
            "chunk_count": None,
            "datagram": (b"\x80\x01" + carrier.to_bytes(2, "big")
                         + marshal_datagram([rec])).hex(),
        }
    )


def send_message(body: bytes, out: Out, frames: list[dict]) -> None:
    """`rep.py::_send_replay_message`, minus the socket."""
    inner = encode_vlq32(len(body)) + body
    seq = out.message
    out.message = (seq + 1) & 0xFFFF
    rel = out.reliable
    out.reliable = (rel + 1) & 0xFFFF
    if len(inner) <= REPLAY_SINGLE_LIMIT:
        rec = MessageRecord(
            channel=0,
            payload=inner,
            sequence=seq,
            reliable_sequence=rel,
            reliable=True,
            connecting=False,
            flags_override=0x21,
        )
        carrier = out.take_envelope()
        frames.append(
            {
                "envelope": carrier,
                "chunk_index": None,
                "chunk_count": None,
                "datagram": (b"\x80\x01" + carrier.to_bytes(2, "big")
                             + marshal_datagram([rec])).hex(),
            }
        )
        return
    chunks = chunk_replay_payload(inner, REPLAY_CHUNK_SIZE)
    for index, (remaining, sl) in enumerate(chunks):
        if index == 0:
            c_seq, c_rel = seq, rel
        else:
            c_seq = out.message
            out.message = (c_seq + 1) & 0xFFFF
            c_rel = out.reliable
            out.reliable = (c_rel + 1) & 0xFFFF
        rec = MessageRecord(
            channel=0,
            payload=sl,
            sequence=c_seq,
            reliable_sequence=c_rel,
            reliable=True,
            connecting=False,
            num_chunks=(len(chunks) if REPLAY_CHUNK_COUNT_TOTAL else remaining),
            flags_override=0x25,
        )
        carrier = out.take_envelope()
        frames.append(
            {
                "envelope": carrier,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "datagram": (b"\x80\x01" + carrier.to_bytes(2, "big")
                             + marshal_datagram([rec])).hex(),
            }
        )


def frame(raw: bytes) -> dict:
    tail = raw[4:]
    flags = tail[0]
    size = int.from_bytes(tail[1:3], "big")
    cursor = 3
    channel = None
    if flags & 0x20:
        channel = tail[cursor]
        cursor += 1
    chunks = None
    if flags & 0x04:
        chunks = int.from_bytes(tail[cursor:cursor + 2], "big")
        cursor += 2
    seq = int.from_bytes(tail[cursor:cursor + 2], "big")
    cursor += 2
    rel = int.from_bytes(tail[cursor:cursor + 2], "big")
    cursor += 2
    return {
        "flags": flags,
        "size": size,
        "channel": channel,
        "num_chunks": chunks,
        "sequence": seq,
        "reliable_sequence": rel,
        "payload_len": len(tail) - cursor,
        "length": len(raw),
    }


def main() -> None:
    inbound_v3_seq = int(sys.argv[1], 0) if len(sys.argv) > 1 else 5
    clock = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x99479CB9
    # `PeerSession.on_app_data`: next_out_seq = max(1, inbound.sequence + 1), and
    # the V3 answer is built with client_env_seq + 1 WITHOUT consuming it.
    out = Out(inbound_v3_seq + 1)
    frames: list[dict] = []
    # `PeerSession.tick` order: maybe_keepalive() then maybe_pump_replay().
    keepalive(out, clock, frames)
    # The capture's first post-registration record is the 0x15d ping, and the
    # reference's own `heartbeat_body` reproduces the captured 12 bytes from its
    # tick alone. The tick comes from the corpus body: the card reads it as a
    # 48-bit big-endian counter, so the last 6 bytes are the integer.
    ping_body = wire_body(0x15D)
    tick = int.from_bytes(ping_body[2:], "big")
    assert heartbeat_body(tick) == typed_body(0x15D, ping_body), (
        "the reference's heartbeat_body must reproduce the captured 0x15d record"
    )
    heartbeat_frames: list[dict] = []
    send_message(typed_body(0x15D, ping_body), out, heartbeat_frames)
    # Then the once-each rungs, in the capture's order.
    for body in (
        typed_body(0x40A, wire_body(0x40A)),
        typed_body(0x1BE, wire_body(0x1BE)),
        typed_body(0x65C, wire_body(0x65C)),
        # `ReceivePlayerSpawnPointMsg` has no body: the record is the typed
        # header alone, which the corpus holds as 00 01 91 19 at seq 0x07.
        typed_body(0x651, b""),
        typed_body(0x663, wire_body(0x663)),
        state_bundle_body("0x9e_T0x8_R.bin"),
    ):
        send_message(body, out, frames)

    def painted(entries: list[dict]) -> list[dict]:
        out_rows = []
        for entry in entries:
            raw = bytes.fromhex(entry["datagram"])
            out_rows.append({**entry, **frame(raw), "fnv1a64": fnv1a64(raw)})
        return out_rows

    keepalive_rows = painted(frames[:1])
    heartbeat_rows = painted(heartbeat_frames)
    ladder_rows = painted(frames[1:])
    print(
        f"# inbound_v3_seq={inbound_v3_seq} clock={clock:#010x} "
        f"datagrams={len(keepalive_rows) + len(heartbeat_rows) + len(ladder_rows)}"
    )
    for name, rows in (
        ("ORACLE_HEARTBEAT", heartbeat_rows),
        ("ORACLE_LADDER", ladder_rows),
    ):
        print(f"# {name} ({len(rows)} records)")
        for index, item in enumerate(rows):
            print(
                f"    ({item['envelope']:#06x}, {item['flags']:#04x}, {item['size']:5d}, "
                f"{item['num_chunks'] if item['num_chunks'] is not None else 1:5d}, "
                f"{item['sequence']:5d}, {item['reliable_sequence']:5d}, "
                f"{item['fnv1a64']:#018x}),  // {index}"
            )


if __name__ == "__main__":
    main()