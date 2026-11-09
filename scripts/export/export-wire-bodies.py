"""Extract one real message BODY per target wire layout, reproducibly, by tool.

WHY THIS EXISTS
===============
`research/fixtures/wire/wire-fixtures.json` holds whole datagrams and state
bundles. A field-by-field codec needs something narrower: for one layout, the
exact BODY bytes, so the generated codec can be required to reproduce them
byte-for-byte. This extractor finds those bodies and writes
`research/fixtures/wire/wire-bodies.json`.

It NEVER hand-pastes bytes. Each body is pulled out of a real source:

  - the committed corpus `services/world/replay/messages-redacted.txt`, whose
    blocks are the official server->client records (a record payload is the
    typed header `00 01 <prefix-varint type>` then the body); and
  - a local structured log (`world.log`-style or `rep_traffic.jsonl`), whose
    `app-data` events replay the client's own datagrams. A client channel-0
    record carries the typed header at offset 24, after the 8-byte frame head
    and the 16-byte actor id, so both offsets 0 and 24 are tried.

A target with no bytes in either source is reported as not found; it is a
`typed but unverified` layout, never a fabricated fixture.

Usage:
    python scripts/export/export-wire-bodies.py
    python scripts/export/export-wire-bodies.py --log .azoth/logs/world.log \
        --out research/fixtures/wire/wire-bodies.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "wire"))
sys.path.insert(0, str(ROOT / "services" / "world" / "src"))
from logwire import decode_varint, split_records  # noqa: E402
from azoth_world.javelin import varint as _varint  # noqa: E402

CORPUS = ROOT / "services" / "world" / "replay" / "messages-redacted.txt"
DEFAULT_LOGS = (
    ROOT / ".azoth" / "logs" / "world.log",
    ROOT / "services" / "world" / "rep_traffic.jsonl",
)
DATA_CHANNELS = (0, 1, 2)
MAX_BODIES_PER_WIRE = 8

# The layouts this extractor knows how to name. Every wire here is a target of
# the seeding task; one without bytes is reported, not invented.
TARGETS: dict[int, str] = {
    0x3: "RegistrationResponseMsg",
    # The three records the capture sends BEFORE the self-identification record
    # (corpus seq 0x2, 0x4, 0x5). All three are server->client, so their bodies are
    # in the committed corpus and nowhere else.
    0x15d: "PingMsg",
    0x40a: "CalendarConnectedMsg",
    0x1be: "CoatlicueTimingConfigurationConnectedMsg",
    0x663: "LevelInfoChangedMsg",
    0x65c: "PlayerManagerSelfIdentificationMsg",
    # The only remaining server->client type in the corpus: a map of notification
    # pairs. It is S2C, so its body is in the committed corpus.
    0xca4: "EventNotificationComponentClientFacet_SyncNotifications",
    0x8: "ReplicatedStateBundle (spawn record)",
    0x5de: "AttributeComponentServerFacet_RequestSpendAttributePoints",
    0xf37: "PaperdollComponentServerFacet_ServerEquipItem",
    # The six inbound requests the SERVER-CONTRACT orders a playable world to
    # answer. All six are client -> server, so their bodies are in a client
    # channel-0/1 record (a local log), never in the server->client corpus.
    0x9d3: "PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient",
    0x5b2: "ObjectivesComponentServerFacet_UpdateTrackedObjectives",
    0xa95: "ObjectivesComponentServerFacet_SetObjectiveAutoPinning",
    0x9fc: "ContractsComponentServerFacet_LookupContractsByParticipant",
    0x183: "GlobalStorageComponentServerFacet_SetReplicateStorage",
    0x1098: "TimeComponentServerFacet_SyncToClient",
    # The next decoded inbound requests whose bodies are actually in a local
    # session log. 0xa39 fires on every panel transition and 0x8f9 on a
    # territory-unlock attempt; both are C2S, so only a client channel-0/1
    # record (a local log) carries them.
    0xa39: "ObjectivesComponentServerFacet_NotifyOpenUiScreen",
    0x8f9: "TerritoryDetectorComponentServerFacet_AttemptTerritoryUnlock",
}


def _load_blocks(path: Path) -> dict[str, bytes]:
    """Reuse the corpus hexdump reader (honours `XX` redaction as 0x00)."""
    spec = importlib.util.spec_from_file_location(
        "measure_inventory_grammar",
        ROOT / "scripts" / "measure" / "measure-inventory-grammar.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_blocks(path)


def _markers() -> dict[int, bytes]:
    return {wire: b"\x00\x01" + _varint.encode(wire) for wire in TARGETS}


def _from_corpus(blocks: dict[str, bytes], wire: int) -> dict | None:
    marker = _markers()[wire]
    suffix_a = f"_T0x{wire:X}_R.bin"
    suffix_b = f"_T0x{wire:x}_R.bin"
    # Several blocks can carry the same wire type; the record's own block is the one
    # whose typed header sits EARLIEST (a datagram-framed block puts it later, and a
    # later `00 01 <type>` may be a coincidental run inside the body).
    best: tuple[str, int, bytes] | None = None
    for name in sorted(blocks):
        data = blocks[name]
        if suffix_a not in name and suffix_b not in name:
            continue
        pos = data.find(marker)
        if pos < 0:
            continue
        if best is None or pos < best[1] or (pos == best[1] and name < best[0]):
            best = (name, pos, data)
    if best is None:
        return None
    name, pos, data = best
    _, end = decode_varint(data, pos + 2)
    return {
        "wire_id": wire,
        "name": TARGETS[wire],
        "channel": None,
        "marker_offset": pos,
        "header_len": end - pos,
        "payload_len": len(data) - pos,
        "body": data[end:].hex(),
        "source": f"corpus:{name}",
    }


def _scan_logs(logs: list[Path]) -> dict[int, list[dict]]:
    """Scan each log ONCE and bucket client records by target wire id."""
    markers = _markers()
    marker_hex = {m.hex(): wire for wire, m in markers.items()}
    out: dict[int, list[dict]] = {wire: [] for wire in TARGETS}
    seen: dict[int, set[str]] = {wire: set() for wire in TARGETS}
    for path in logs:
        if not path.is_file():
            continue
        # Read lines directly so only lines that actually carry a target marker are
        # JSON-parsed: the 11 GB traffic log is mostly irrelevant records.
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not any(hex_marker in line for hex_marker in marker_hex):
                    continue
                brace = line.find("{")
                if brace < 0:
                    continue
                try:
                    ev = json.loads(line[brace:])
                except ValueError:
                    continue
                if ev.get("event") != "app-data":
                    continue
                raw_hex = ev.get("raw")
                if not raw_hex:
                    continue
                candidates = [
                    (wire, markers[wire]) for hex_marker, wire in marker_hex.items()
                    if hex_marker in raw_hex
                ]
                if not candidates:
                    continue
                try:
                    raw = bytes.fromhex(raw_hex)
                except ValueError:
                    continue
                try:
                    records = split_records(raw)
                except (IndexError, ValueError):
                    continue
                for channel, payload in records:
                    if channel not in DATA_CHANNELS:
                        continue
                    for offset in (0, 24):
                        for wire, marker in candidates:
                            end = offset + len(marker)
                            if payload[offset:end] != marker:
                                continue
                            _, body_start = decode_varint(payload, offset + 2)
                            body = payload[body_start:]
                            key = body.hex()
                            if key in seen[wire]:
                                continue
                            seen[wire].add(key)
                            if len(out[wire]) >= MAX_BODIES_PER_WIRE:
                                continue
                            out[wire].append(
                                {
                                    "wire_id": wire,
                                    "name": TARGETS[wire],
                                    "channel": channel,
                                    "marker_offset": offset,
                                    "header_len": body_start - offset,
                                    "payload_len": len(payload),
                                    "body": key,
                                    "source": f"log:{path.name}@{ev.get('ts', '?')}",
                                }
                            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--corpus", default=str(CORPUS), help="committed replay dump (server->client)"
    )
    ap.add_argument(
        "--log",
        action="append",
        default=None,
        help="local structured log to scan for client records (repeatable)",
    )
    ap.add_argument("--out", default=str(ROOT / "research" / "fixtures" / "wire" / "wire-bodies.json"))
    args = ap.parse_args()

    blocks = _load_blocks(Path(args.corpus)) if Path(args.corpus).is_file() else {}
    logs = [Path(p) for p in (args.log or [str(p) for p in DEFAULT_LOGS])]
    logged = _scan_logs(logs)

    records: list[dict] = []
    report: list[tuple[int, str, str]] = []
    for wire in sorted(TARGETS):
        corpus = _from_corpus(blocks, wire)
        if corpus is not None:
            records.append(corpus)
            report.append((wire, TARGETS[wire], corpus["source"]))
        log_bodies = logged.get(wire, [])
        for body in log_bodies:
            records.append(body)
        if log_bodies:
            report.append((wire, TARGETS[wire], log_bodies[0]["source"] + f" (+{len(log_bodies) - 1})"))
        if corpus is None and not log_bodies:
            report.append((wire, TARGETS[wire], "NOT FOUND"))

    out = {
        "$comment": (
            "One real message BODY per target layout, extracted by "
            "scripts/export/export-wire-bodies.py from the committed corpus and a "
            "local structured log. Every body is reproducible by re-running the "
            "tool; nothing here is hand-pasted. A target with no source is absent "
            "and is a 'typed but unverified' layout."
        ),
        "build_sha256": "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033",
        "records": records,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")

    print(f"wrote {out_path}")
    print(f"  records: {len(records)}")
    print("per-layout source:")
    for wire, name, source in report:
        print(f"  0x{wire:x} {name}: {source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
