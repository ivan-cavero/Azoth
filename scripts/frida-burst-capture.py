#!/usr/bin/env python3
"""Capture the ONE replay burst: which replay messages the client actually processes.

WHY. The replay is a ~3 s burst right after the world entry; attaching later
measures an idle process and every counter reads 0 (an attach-timing artifact
that produced a wrong "the pipeline is dead" conclusion on 2026-09-30).
This probe must be attached BEFORE the client enters the world.

It counts, per stage of the type-0x08 bundle pipeline:
  FUN_146af20d0  bundle split            (per state-bundle message)
  FUN_141717fc0  record visitor          (per record; collected from EDX)
  FUN_14178db00  portrayal               (per entity)
  FUN_1415e68b0  portrayal-table insert  (per entity)
  FUN_14178ec80  removal/destruction     (not actor creation)
  FUN_141563e20  actor factory           (per actor)
and dumps a snapshot every 5 s so the burst is visible in the timeline.

Read-only. Run with the Windows python (frida 17):

  "C:/Users/ivang/AppData/Local/Python/bin/python.exe" scripts/frida-burst-capture.py

Usage: launch it right after `az.py game`, then enter the world by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import frida

LOG = Path(r"C:\Users\ivang\AppData\Local\Temp\azoth-burst-capture.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

const counters = {
  split: 0, visitor: 0, portray: 0, insert: 0, remove: 0, factory: 0,
  localBuilder: 0, managerDispatch: 0, managerSetContext: 0,
};
const recordIds = {};
const portrayByRecord = {};
const insertByRecord = {};
const factoryByRecord = {};
const recordStackByThread = {};

function hook(va, name, cb) {
  try {
    Interceptor.attach(at(va), { onEnter(args) { cb(args, this); } });
    return true;
  } catch (e) {
    send({ ev: 'hook-fail', f: name, err: String(e).slice(0, 80) });
    return false;
  }
}

hook(0x146af20d0, 'split', () => { counters.split++; });

// FUN_141717fc0(rcx=state, edx=record id, r8=fragment cursor). Keep a stack
// because a visitor can be nested while processing the same synchronous burst.
const visitor = Interceptor.attach(at(0x141717fc0), {
  onEnter(args) {
    counters.visitor++;
    const id = this.context.rdx.toInt32() & 0xffff;
    const tid = Process.getCurrentThreadId().toString();
    this.tid = tid;
    if (recordStackByThread[tid] === undefined) recordStackByThread[tid] = [];
    recordStackByThread[tid].push(id);
    recordIds[id] = (recordIds[id] || 0) + 1;
  },
  onLeave() {
    const stack = recordStackByThread[this.tid];
    if (stack !== undefined) stack.pop();
  }
});

function currentRecord() {
  const stack = recordStackByThread[Process.getCurrentThreadId().toString()];
  return stack && stack.length ? stack[stack.length - 1] : null;
}
function countFor(map, id) {
  if (id !== null) map[id] = (map[id] || 0) + 1;
}

function safeRead(fn) {
  try { return fn(); } catch (_) { return null; }
}
function qword(p, off) {
  return safeRead(() => p.add(off).readPointer().toString());
}
function managerFields(p) {
  return { context: qword(p, 8), contextRef: qword(p, 0x10), third: qword(p, 0x18) };
}
const managerEvents = [];
function keepManagerEvent(ev) {
  if (managerEvents.length < 500) managerEvents.push(ev);
}

// The InGame state dispatches a context association through the manager vtable.
// Log the gate fields and the concrete setter arguments to distinguish a
// missing call from a call that stores an unusable context.
hook(0x146764cd0, 'manager-dispatch', (args, invocation) => {
  counters.managerDispatch++;
  const state = args[0];
  const base = {
    ev: 'manager-dispatch', t: Date.now(),
    state: state.toString(),
    status: safeRead(() => state.add(0x318).readU32()),
    gate: safeRead(() => state.add(0x31c).readU8()),
    done: safeRead(() => state.add(0x31d).readU8()),
  };
  invocation.managerDispatch = base;
  keepManagerEvent(base);
});
Interceptor.attach(at(0x146928d80), {
  onEnter(args) {
  counters.managerSetContext++;
  const manager = args[0];
  const context = args[1];
  const ev = {
    ev: 'manager-set-context', t: Date.now(),
    manager: manager.toString(), context: context.toString(),
    before: managerFields(manager),
    contextRef: { owner: qword(context, 0x38), first: qword(context, 0x48), second: qword(context, 0x50) },
  };
  this.managerSetContext = { manager: manager, event: ev };
  keepManagerEvent(ev);
  },
  onLeave() {
    const s = this.managerSetContext;
    if (s) s.event.after = managerFields(s.manager);
  }
});
hook(0x1416957c0, 'local-player-prototype-builder', () => {
  counters.localBuilder++;
});

hook(0x14178db00, 'portray', () => {
  counters.portray++;
  countFor(portrayByRecord, currentRecord());
});
hook(0x1415e68b0, 'insert', () => {
  counters.insert++;
  countFor(insertByRecord, currentRecord());
});
// FUN_14178ec80 removes/destroys a portrayal; it is not the create path.
hook(0x14178ec80, 'remove', () => { counters.remove++; });
hook(0x141563e20, 'factory', () => {
  counters.factory++;
  countFor(factoryByRecord, currentRecord());
});

setInterval(() => {
  send({ ev: 'tick', counters: counters, records: recordIds,
    portrayByRecord: portrayByRecord, insertByRecord: insertByRecord,
    factoryByRecord: factoryByRecord, managerEvents: managerEvents });
}, 5000);
send({ ev: 'ready' });
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=LOG, help="append JSONL evidence here")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    logf = args.log.open("a", encoding="utf-8")
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)

    def on_msg(m, _d) -> None:
        payload = m.get("payload")
        line = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    script.on("message", on_msg)
    script.load()
    print("[burst] attached — enter the world now (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
