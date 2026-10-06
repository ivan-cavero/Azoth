#!/usr/bin/env python3
"""Wait for the next replay burst and dump the local-player slot state.

WHY. The type-0x08 pipeline runs only during a short burst right after the
world entry. Attaching afterwards measures an idle process. Record counts and
creation/removal hooks must be correlated to that run; a zero recorded outside
the burst means the probe attached too late, not that the path never ran.

At the FIRST record-visitor call it captures:
  * the visitor's `state` (rcx) and the four local-player slots
    `state + 0x608 + id*0x10` (the LocalPlayer holder array);
  * the manager singleton and its `[mgr+8]` / `[mgr+0x10]` pair;
  * every record id the visitor is called with;
  * per-stage counters for the whole burst.
A snapshot follows every 5 s so the burst is visible in time.

Read-only. Run with the Windows python (frida 17):

  python reverse/probes/client/frida-slot-watch.py  # use an interpreter with frida installed
"""

from __future__ import annotations

import json
import argparse
import time
from pathlib import Path

import frida
from _paths import project_log

LOG = project_log("slot-watch.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

const counters = { split: 0, visitor: 0, portray: 0, insert: 0, remove: 0, factory: 0 };
const recordIds = {};
let stateSlotDump = null;
let localPlayerSamples = 0;

function hook(va, name, cb) {
  try { Interceptor.attach(at(va), { onEnter(args) { cb(args, this); } }); }
  catch (e) { send({ ev: 'hook-fail', f: name, err: String(e).slice(0, 80) }); }
}

hook(0x146af20d0, 'split', () => { counters.split++; });
hook(0x14178db00, 'portray', () => { counters.portray++; });
hook(0x1415e68b0, 'insert', () => { counters.insert++; });
hook(0x14178ec80, 'remove', () => { counters.remove++; });
hook(0x141563e20, 'factory', () => { counters.factory++; });

// FUN_141717fc0(rcx=state, dx=record id, r8=fragment cursor).
Interceptor.attach(at(0x141717fc0), {
  onEnter(args) {
    counters.visitor++;
    try { this.id = this.context.rdx.toInt32() & 0xffff; } catch (e) { this.id = -1; }
    this.state = args[0];
    if (this.id >= 0) recordIds[this.id] = (recordIds[this.id] || 0) + 1;

    if (stateSlotDump === null) {
      try {
        const s = args[0];
        const slots = {};
        for (let i = 0; i < 4; i++) {
          slots[i] = s.add(0x608 + i * 0x10).readPointer().toString();
        }
        const mgr = new NativeFunction(at(0x141026080), 'pointer', [], 'win64')();
        stateSlotDump = {
          state: s.toString(),
          slots: slots,
          mgr: mgr.toString(),
          mgr_f8: mgr.add(8).readPointer().toString(),
          mgr_f10: mgr.add(0x10).readPointer().toString(),
        };
        send({ ev: 'FIRST-VISITOR', dump: stateSlotDump });
      } catch (e) {
        send({ ev: 'dump-error', err: String(e).slice(0, 120) });
      }
    }

    if (this.id === 1 && localPlayerSamples < 4) {
      try {
        const slot = this.state.add(0x618);
        this.localBefore = {
          entity: slot.readPointer().toString(),
          metadata: slot.add(8).readPointer().toString(),
        };
      } catch (e) {
        this.localBefore = { error: String(e).slice(0, 120) };
      }
    }
  },
  onLeave() {
    if (this.id !== 1 || localPlayerSamples >= 4) return;
    localPlayerSamples++;
    try {
      const slot = this.state.add(0x618);
      const mgr = new NativeFunction(at(0x141026080), 'pointer', [], 'win64')();
      send({
        ev: 'LOCAL-PLAYER-RECORD',
        sample: localPlayerSamples,
        state: this.state.toString(),
        before: this.localBefore,
        after: {
          entity: slot.readPointer().toString(),
          metadata: slot.add(8).readPointer().toString(),
        },
        manager: mgr.toString(),
        holderEntity: mgr.add(8).readPointer().toString(),
        holderReady: mgr.add(0x10).readPointer().toString(),
      });
    } catch (e) {
      send({ ev: 'LOCAL-PLAYER-RECORD-ERROR', err: String(e).slice(0, 120) });
    }
  }
});

setInterval(() => {
  send({ ev: 'tick', counters: counters, recordIds: recordIds, dump: stateSlotDump });
}, 5000);
send({ ev: 'ready' });
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="exact NewWorld.exe PID")
    parser.add_argument("--log", type=Path, default=LOG, help="append JSONL evidence here")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    logf = args.log.open("a", encoding="utf-8")
    session = frida.attach(args.pid)
    script = session.create_script(JS)

    def on_msg(m, _d) -> None:
        payload = m.get("payload")
        line = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    script.on("message", on_msg)
    script.load()
    print(f"[slot-watch] attached to PID {args.pid} — waiting for the replay burst", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
