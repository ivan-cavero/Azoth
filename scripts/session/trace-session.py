#!/usr/bin/env python3
"""Trace one InGame window: what flowed between "InGame" and disconnect.

Reads rep_traffic.jsonl tail and prints a compact per-datagram timeline
(direction, envelope seq, record summary) so the 3.5s csdkerr_disconnect(2)
window can be compared against the earlier 30s ingame_timeout sessions.
"""
import json
import re
import sys
from pathlib import Path

LOG = Path(__file__).resolve().parents[2] / "services" / "world" / "rep_traffic.jsonl"


def summarize(line: str) -> str | None:
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    ts = ev.get("ts", "")[-9:]
    evn = ev.get("event")
    if evn == "app-data":
        recs = "; ".join(
            f"ch{r['channel']} f{r['flags']} s{r['size']} sys{r.get('system')}"
            for r in ev.get("records", [])
        )
        env = ev.get("envelope", {})
        return f"{ts} IN  seq={env.get('seq')} {recs}"
    if evn == "reply":
        raw = ev.get("raw", "")
        # decode envelope header for seq
        try:
            seq = int(raw[4:8], 16)
        except ValueError:
            seq = -1
        return f"{ts} OUT seq={seq} size={ev.get('size')}"
    if evn in ("keepalive", "resend", "v3-registered", "replay-armed", "dtls-established"):
        extra = {k: v for k, v in ev.items() if k not in ("ts", "event", "raw", "peer")}
        return f"{ts} {evn.upper()} {extra}"
    return None


def main() -> int:
    lines = LOG.read_text(encoding="utf-8").splitlines()
    # find the last dtls-established and print everything after it
    start = 0
    for i, line in enumerate(lines):
        if '"event": "dtls-established"' in line:
            start = i
    for line in lines[start:]:
        s = summarize(line)
        if s:
            print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
