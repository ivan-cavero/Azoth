"""Inventory of what the CLIENT asks our server for, from a captured world session.

WHY THIS EXISTS
===============
The question "does our server have everything the client expects?" had no measurable answer.
This tool produces one: it decodes every client->server record in a session log and lists, per
wire type, the NAME of the message, how many times the client sent it, and what KIND of thing
it is (a request the client expects an answer to, a fire-and-forget notification, transport).

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

NAMES COME FROM THREE REGISTRIES, IN THIS ORDER
===============================================
1. `research/derived/wire-type-names.json` -- the build's own type table, named from the
   brace-wrapped `<Name>\\0...\\0<GUID>` descriptor form in `.rdata` (2201 of 7052 named).
2. `research/atlas/javelin-messages.json` -- the hand-curated Javelin message registry
   (name + GUID + wire index), by wire index and by GUID.
3. `research/atlas/az-type-registry.json` -- every AZ type the build registers, by GUID.

A type that none of the three can name is reported as `?` rather than guessed: several wire
types are not Javelin-typed at all and belong to another registry (the Carrier/system channel
carries a 4-byte non-typed record, and the client's V3 re-registration is not in the type
table). Each row keeps the GUID it decoded, so an unnamed type is still addressable.

CLASSIFICATION
==============
Every client->server record gets one `kind`:

  transport        keepalive/ack, answered by the transport layer (PingMsg, Carrier records)
  input-stream     the ActionListComponent input stream (the client's own movement input)
  v3-registration  the client's RegistrationRequestV3 (session setup, answered once)
  request          a `*ComponentServerFacet_<Method>` message: a typed call on a server facet
  notification     a typed message with no facet target (client state reporting)
  unknown          not classified; keep the row visible, do not guess

The distinction that matters for the server is request vs notification: a request is the
client waiting for an answer, a notification is not. `kind` is derived from the message name
and the wire id, never from a payload guess.

Usage:
    python scripts/inbound-inventory.py .azoth/logs/world.log
    python scripts/inbound-inventory.py <log> --session last    # only the last session
    python scripts/inbound-inventory.py <log> --json out.json
    python scripts/inbound-inventory.py --check                 # self-test, writes nothing
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
JAVELIN = ROOT / "research" / "atlas" / "javelin-messages.json"
AZ_REGISTRY = ROOT / "research" / "atlas" / "az-type-registry.json"

# Wire ids with a fixed, measured role that is not in any name registry.
TRANSPORT_TYPES = {349}          # PingMsg, answered by the transport layer
INPUT_STREAM_TYPES = {1589}      # ActionListComponentServerFacet_ReceiveInputFromClient
V3_REGISTRATION_TYPES = {19}     # RegistrationRequestV3Msg (the client's V3 re-registration)


def _load_names() -> dict[int, dict]:
    """wire type -> {name, source, guid}. First source that names it wins."""
    out: dict[int, dict] = {}
    if NAMES.is_file():
        data = json.loads(NAMES.read_text(encoding="utf-8"))
        for row in data["names"]:
            out[row["wire_type"]] = {
                "name": row.get("name"),
                "source": row.get("source"),
                "guid": row.get("guid"),
            }
    # Javelin registry: fill gaps by wire index and by GUID.
    if JAVELIN.is_file():
        data = json.loads(JAVELIN.read_text(encoding="utf-8"))
        by_guid = {}
        for row in data.get("messages", []):
            guid = str(row.get("guid") or "").lower()
            if guid:
                by_guid[guid] = row["name"]
            wire = row.get("wire_type")
            if wire is not None and not out.get(wire, {}).get("name"):
                out.setdefault(wire, {"guid": None})["name"] = row["name"]
                out[wire]["source"] = "javelin-registry"
        for wire, row in out.items():
            if not row.get("name"):
                guid = str(row.get("guid") or "").lower()
                if guid in by_guid:
                    row["name"] = by_guid[guid]
                    row["source"] = "javelin-registry"
    # AZ registry: last resort, by GUID.
    if AZ_REGISTRY.is_file():
        data = json.loads(AZ_REGISTRY.read_text(encoding="utf-8"))
        by_guid = {}
        for entry in data.get("types", []):
            guid = str(entry.get("guid") or "").lower()
            if guid and entry.get("name"):
                by_guid.setdefault(guid, entry["name"])
        for row in out.values():
            if not row.get("name"):
                guid = str(row.get("guid") or "").lower()
                if guid in by_guid:
                    row["name"] = by_guid[guid]
                    row["source"] = "az-registry"
    return out


def classify(wire_type: int, channel: int, name: str | None) -> str:
    if channel == 3:
        return "transport"
    if wire_type in V3_REGISTRATION_TYPES:
        return "v3-registration"
    if wire_type in INPUT_STREAM_TYPES:
        return "input-stream"
    if wire_type in TRANSPORT_TYPES or name == "PingMsg":
        return "transport"
    if name and "ServerFacet_" in name:
        return "request"
    if name:
        return "notification"
    return "unknown"


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


def scan(lines: list[str]) -> tuple[list[dict], dict]:
    """Decode a session's client->server records into per-type inventory rows."""
    per_channel_type: dict[tuple[int, int], int] = collections.Counter()
    channel_records: collections.Counter = collections.Counter()
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
            channel_records[record.channel] += 1
            type_id, _ = decode(record)
            if type_id is None:
                continue
            per_channel_type[(record.channel, type_id)] += 1

    names = _load_names()
    by_type: dict[int, dict] = {}
    for (channel, type_id), count in per_channel_type.items():
        row = by_type.setdefault(
            type_id,
            {
                "wire_type": type_id,
                "name": None,
                "source": None,
                "guid": None,
                "channels": [],
                "count": 0,
                "kind": "unknown",
            },
        )
        row["count"] += count
        if channel not in row["channels"]:
            row["channels"].append(channel)
    for type_id, row in by_type.items():
        info = names.get(type_id) or {}
        row["name"] = info.get("name")
        row["source"] = info.get("source")
        row["guid"] = info.get("guid")
        row["kind"] = classify(type_id, row["channels"][0], row["name"])
        row["channels"].sort()
    rows = sorted(by_type.values(), key=lambda r: -r["count"])
    stats = {
        "datagrams_parsed": parsed,
        "datagrams_unparsed": failed,
        "records_by_channel": dict(sorted(channel_records.items())),
    }
    return rows, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", nargs="?", default=str(ROOT / ".azoth" / "logs" / "world.log"))
    ap.add_argument("--session", choices=["last", "all"], default="last")
    ap.add_argument("--json")
    ap.add_argument("--check", action="store_true", help="self-test the name/classify pipeline")
    args = ap.parse_args()

    if args.check:
        return _self_check()

    lines = Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines()
    if args.session == "last":
        lines = last_session(lines)
    rows, stats = scan(lines)

    print(f"session datagrams parsed {stats['datagrams_parsed']}, "
          f"unparsed {stats['datagrams_unparsed']}")
    print(f"records by channel: {stats['records_by_channel']}")
    print()
    print(f"{'wire':>6} {'count':>7}  {'channels':<10} {'kind':<16} name")
    for row in rows:
        name = row["name"] or "?"
        print(f"{row['wire_type']:6d} {row['count']:7d}  {str(row['channels']):<10} "
              f"{row['kind']:<16} {name}")
    kinds = collections.Counter(r["kind"] for r in rows)
    requests = [r for r in rows if r["kind"] == "request"]
    print()
    print(f"{len(rows)} distinct client->server types "
          f"({kinds['request']} requests, {kinds['notification']} notifications, "
          f"{kinds['unknown']} unclassified)")
    print(f"kinds: {dict(kinds)}")
    if args.json:
        payload = {
            "session": args.session,
            "stats": stats,
            "types": rows,
            "request_types": [r["wire_type"] for r in requests],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


def _self_check() -> int:
    """Assert the pipeline still names and classifies the anchors the project verified.

    These are hand-checked facts; if a registry regeneration breaks one, the tool is lying
    about the inventory and must fail loudly rather than emit a plausible table.
    """
    names = _load_names()
    anchors = {
        349: "PingMsg",
        1589: "ActionListComponentServerFacet_ReceiveInputFromClient",
        19: "RegistrationRequestV3Msg",
        2556: "ContractsComponentServerFacet_LookupContractsByParticipant",
        4248: "TimeComponentServerFacet_SyncToClient",
        2515: "PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient",
        7048: "GlobalStorageComponentClientFacet_ReceiveStorageSearchItems",
    }
    bad = []
    for wire, expected in anchors.items():
        got = (names.get(wire) or {}).get("name")
        if got != expected:
            bad.append(f"{wire}: expected {expected!r}, got {got!r}")
    checks = [
        (classify(349, 0, "PingMsg") == "transport", "349 must be transport"),
        (classify(1589, 1, None) == "input-stream", "1589 must be input-stream"),
        (classify(19, 0, None) == "v3-registration", "19 must be v3-registration"),
        (classify(2556, 0, names[2556]["name"]) == "request", "2556 must be a request"),
        (classify(7048, 0, names[7048]["name"]) == "notification", "7048 must be a notification"),
        (classify(62, 3, None) == "transport", "channel 3 must be transport"),
        (classify(6745, 0, None) == "unknown", "unnamed must stay unknown"),
    ]
    bad += [msg for ok, msg in checks if not ok]
    if bad:
        print("inbound-inventory self-check FAILED:")
        for line in bad:
            print(f"  - {line}")
        return 1
    print(f"inbound-inventory self-check OK: {len(anchors)} names, {len(checks)} classifications")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
