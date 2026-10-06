#!/usr/bin/env python3
"""Read the current local-player holder pointers once in the private client.

Build-specific for NewWorld 1.400.6031.6004151. It observes the getter at
FUN_146800d10 and reads only its two pointer fields; it performs no writes.
Use only after confirming EAC is inactive. The snapshot is ephemeral runtime
evidence and belongs in ignored research/sessions/, never in the atlas.
"""

from __future__ import annotations

import argparse
import json
import queue
import time
from datetime import UTC, datetime
from pathlib import Path

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ev: 'error', error: 'NewWorld.exe module not found'});
} else {
  const base = mod.base;
  const target = base.add(0x146800d10 - 0x140000000);
  let done = false;
  let listener = null;
  listener = Interceptor.attach(target, {
    onEnter(args) {
      if (done) return;
      done = true;
      const inner = args[0];
      try {
        const entity = inner.add(8).readPointer();
        const readyPtr = inner.add(0x10).readPointer();
        let flag = null;
        if (!readyPtr.isNull()) flag = readyPtr.readU8();
        send({
          ev: 'snapshot',
          moduleBase: base.toString(),
          moduleSize: mod.size,
          getterVa: '0x146800d10',
          inner: inner.toString(),
          entitySlot: inner.add(8).toString(),
          entity: entity.toString(),
          readyPointerSlot: inner.add(0x10).toString(),
          readyPtr: readyPtr.toString(),
          readyFlag: flag
        });
      } catch (e) {
        send({ev: 'read-error', error: String(e)});
      }
      listener.detach();
    }
  });
  setTimeout(() => {
    if (!done) {
      send({ev: 'timeout', getterVa: '0x146800d10'});
      listener.detach();
    }
  }, 7000);
}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="NewWorld.exe PID")
    parser.add_argument("--out", type=Path, help="optional ignored JSON evidence file")
    args = parser.parse_args()

    messages: queue.Queue[dict] = queue.Queue()
    session = frida.attach(args.pid)
    script = session.create_script(JS)
    script.on(
        "message",
        lambda message, _data: messages.put(message.get("payload", message)),
    )
    try:
        script.load()
        result = messages.get(timeout=9)
    except queue.Empty:
        print("timed out waiting for the local-player getter")
        return 2
    finally:
        script.unload()
        session.detach()

    record = {
        "captured_utc": datetime.now(UTC).isoformat(),
        "pid": args.pid,
        "method": "read-only getter interception",
        **result,
    }
    rendered = json.dumps(record, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result.get("ev") == "snapshot" else 1


if __name__ == "__main__":
    raise SystemExit(main())
