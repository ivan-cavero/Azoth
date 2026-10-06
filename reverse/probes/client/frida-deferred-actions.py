#!/usr/bin/env python3
"""Read the Javelin deferred-action queues during a private world attempt.

Build-specific to NewWorld 1.400.6031.6004151. This read-only probe samples
the two 0x50-byte queues consumed by FUN_1416adce0 and records target IDs for
the actions passed through FUN_1416aecc0. Attach only after verifying that
EasyAntiCheat is inactive for the exact process.

Usage:
  python reverse/probes/client/frida-deferred-actions.py --pid <NewWorld PID> \
    --log .azoth/captures/probes/deferred-actions.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) throw new Error('NewWorld.exe module not found');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
const stats = { drains: 0, actionLookups: 0, depthCap: null,
  mainCounts: {}, stagingCounts: {}, targets: {}, vtables: {}, samples: [] };

function sampleQueue(ctx, offset) {
  const begin = ctx.add(offset).readPointer();
  const end = ctx.add(offset + 8).readPointer();
  const size = end.sub(begin).toInt32();
  if (size < 0 || size > 0x100000 || size % 0x50 !== 0) {
    return { bytes: size, count: null, items: [] };
  }
  const count = size / 0x50;
  const items = [];
  for (let i = 0; i < Math.min(count, 16); i++) {
    const item = begin.add(i * 0x50);
    items.push({
      targetEntityId: item.add(0x48).readU64().toString(),
      vtable: item.readPointer().toString()
    });
  }
  return { bytes: size, count: count, items: items };
}

Interceptor.attach(at(0x1416adce0), {
  onEnter(args) {
    stats.drains++;
    try {
      if (stats.depthCap === null) stats.depthCap = at(0x14a321a4c).readU32();
      const main = sampleQueue(args[0], 0x1b8);
      const staging = sampleQueue(args[0], 0x1d8);
      const m = String(main.count);
      const s = String(staging.count);
      stats.mainCounts[m] = (stats.mainCounts[m] || 0) + 1;
      stats.stagingCounts[s] = (stats.stagingCounts[s] || 0) + 1;
      if ((main.count || 0) > 0 || (staging.count || 0) > 0) {
        stats.samples.push({
          utc: new Date().toISOString(),
          main: main,
          staging: staging
        });
        if (stats.samples.length > 24) stats.samples.shift();
      }
    } catch (e) {
      stats.samples.push({ utc: new Date().toISOString(), readError: String(e) });
      if (stats.samples.length > 24) stats.samples.shift();
    }
  }
});

Interceptor.attach(at(0x1416aecc0), {
  onEnter(args) {
    stats.actionLookups++;
    try {
      const target = args[2].readU64().toString();
      const vtable = args[2].sub(0x48).readPointer().toString();
      stats.targets[target] = (stats.targets[target] || 0) + 1;
      stats.vtables[vtable] = (stats.vtables[vtable] || 0) + 1;
    } catch (e) {
      stats.targets.readError = String(e).slice(0, 120);
    }
  }
});

setInterval(() => {
  // Report the live value: callers may set the global after this probe attaches.
  try { stats.depthCap = at(0x14a321a4c).readU32(); }
  catch (e) { stats.depthCap = 'readError: ' + String(e).slice(0, 80); }
  send({ ev: 'tick', pid: Process.id, stats: stats });
  stats.drains = 0;
  stats.actionLookups = 0;
  stats.mainCounts = {};
  stats.stagingCounts = {};
  stats.targets = {};
  stats.vtables = {};
  stats.samples = [];
}, 5000);
send({ ev: 'ready', pid: Process.id, moduleBase: base.toString(),
  depthCapAddress: at(0x14a321a4c).toString() });
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="exact NewWorld.exe PID")
    parser.add_argument("--log", type=Path, required=True, help="append JSONL evidence here")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    messages = args.log.open("a", encoding="utf-8")
    session = frida.attach(args.pid)
    script = session.create_script(JS)

    def on_msg(message, _data) -> None:
        payload = message.get("payload", message)
        record = {"captured_utc": datetime.now(UTC).isoformat(), **payload}
        rendered = json.dumps(record)
        print(rendered, flush=True)
        messages.write(rendered + "\n")
        messages.flush()

    script.on("message", on_msg)
    script.load()
    print(f"[deferred-actions] attached to PID {args.pid}; Ctrl+C to stop", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        script.unload()
        session.detach()
        messages.close()


if __name__ == "__main__":
    raise SystemExit(main())
