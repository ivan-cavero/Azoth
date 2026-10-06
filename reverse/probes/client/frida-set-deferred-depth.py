#!/usr/bin/env python3
"""Temporarily set the private build's deferred-action batch limit in memory.

This is a one-run experiment for NewWorld 1.400.6031.6004151. The default
global is 0, and the drain routine clamps that to one batch per frame. Attach
only to the exact private NewWorld.exe PID after confirming EAC is inactive.
The value disappears when the process exits; it does not modify the executable
or settings files.

Usage:
  python reverse/probes/client/frida-set-deferred-depth.py --pid <PID> --value 16 \
    --eac-verified-inactive --log .azoth/captures/probes/deferred-depth-set.jsonl
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import frida

GLOBAL_VA = 0x14A321A4C
IMAGE_BASE = 0x140000000
JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) throw new Error('NewWorld.exe module not found');
const address = mod.base.add(0x14a321a4c - 0x140000000);
const before = address.readU32();
address.writeU32(VALUE);
const after = address.readU32();
send({ev: 'deferred-depth-set', pid: Process.id,
  moduleBase: mod.base.toString(), address: address.toString(),
  preferredVa: '0x14a321a4c', before: before, requested: VALUE, after: after});
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="exact private NewWorld.exe PID")
    parser.add_argument("--value", type=int, default=16, choices=range(1, 129))
    parser.add_argument(
        "--eac-verified-inactive",
        action="store_true",
        help="required acknowledgement after checking EAC service and this PID's modules",
    )
    parser.add_argument("--log", type=Path, required=True, help="append the before/after evidence here")
    args = parser.parse_args()
    if not args.eac_verified_inactive:
        parser.error("verify EAC is inactive for this exact process before attaching")

    args.log.parent.mkdir(parents=True, exist_ok=True)
    process = next(
        (p for p in frida.get_local_device().enumerate_processes() if p.pid == args.pid),
        None,
    )
    if process is None or process.name.lower() != "newworld.exe":
        parser.error(f"PID {args.pid} is not a running NewWorld.exe process")

    session = frida.attach(args.pid)
    script = session.create_script(JS.replace("VALUE", str(args.value)))
    result: dict[str, object] = {}
    received = threading.Event()

    def on_message(message, _data) -> None:
        payload = message.get("payload")
        if isinstance(payload, dict):
            result.update(payload)
            received.set()

    script.on("message", on_message)
    script.load()
    if not received.wait(timeout=5):
        script.unload()
        session.detach()
        raise RuntimeError("Frida did not return the verified cvar value")
    script.unload()
    session.detach()

    record = {"captured_utc": datetime.now(UTC).isoformat(), **result}
    if result.get("after") != args.value:
        raise RuntimeError(f"depth write did not verify: {record}")
    rendered = json.dumps(record)
    with args.log.open("a", encoding="utf-8") as output:
        output.write(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
