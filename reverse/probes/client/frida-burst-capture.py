#!/usr/bin/env python3
"""Capture the ONE replay burst: which replay messages the client actually processes.

WHY. The replay is a ~3 s burst right after the world entry; attaching later
measures an idle process and every counter reads 0 (an attach-timing artifact
that produced a wrong "the pipeline is dead" conclusion on 2026-09-30).
This probe must be attached BEFORE the client enters the world.

It counts, per stage of the type-0x08 bundle pipeline:
  FUN_145aa23f0  per-frame tick        (CONTROL: if this is 0 the probe is dead)
  FUN_146b6f190  typed-stream dispatch (10-GUID compare after the reader)
  FUN_146b6d180  ring-queue drain      (main-thread object queue)
  FUN_146af20d0  bundle split            (per state-bundle message)
  FUN_141717fc0  record visitor          (per record; collected from EDX)
  FUN_14178db00  portrayal               (per entity)
  FUN_1415e68b0  portrayal-table insert  (per entity)
  FUN_14178ec80  removal/destruction     (not actor creation)
  FUN_141563e20  actor factory           (per actor)
and the gate chain that decides the local-player manager context:
  FUN_14683c8d0  facet option apply      (PlayerComponentClientFacet slot +0xb0)
  FUN_146929df0  option status writer    (writes state+0x318 = 1 or 2)
  FUN_140fca4e0  local option lookup     (thread-local store; found flag at out+0x40)
  FUN_146764cd0  manager gate dispatch   (status +0x31c/+0x31d, calls the setter)
  FUN_146928d80  manager context setter
and dumps a snapshot every 5 s so the burst is visible in the timeline.

On 2026-10-01 a fresh run (PID 23200) had every counter of this probe at 0 while
Game.log showed the 26-message drain and all 43 chunks of the 46 KB bundles
Carrier-ACKed. A zero from this probe is only meaningful next to the CONTROL
counter: `frameTick == 0` means the hooks never ran, not that the pipeline is
dead.

Read-only. Run with the Windows python (frida 17):

  python reverse/probes/client/frida-burst-capture.py  # use an interpreter with frida installed

Usage: launch it right after `ef.py game`. The client enters the world by
itself 2-17 min after launch; attach within the first seconds or the burst is
missed. `reverse/probes/client/frida-reader-capture.py` covers the socket->reader boundary.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida
from _paths import project_log

LOG = project_log("burst-capture.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

const counters = {
  split: 0, visitor: 0, portray: 0, insert: 0, remove: 0, factory: 0,
  localBuilder: 0, managerDispatch: 0, managerSetContext: 0,
  // Control and boundary counters added 2026-10-01. A zero from this probe is
  // only interpretable against frameTick: if the control reads 0, the hooks
  // never ran (attach problem), not the pipeline.
  frameTick: 0, typedDispatch: 0, ringDrain: 0,
  // Two more control candidates: the deferred-action drain runs every frame,
  // the view/camera update too. frameTick (the connection wrapper) only runs
  // while a REP connection exists, so it cannot prove the instrument before
  // the world entry.
  gameTick: 0, viewTick: 0,
  facetApply: 0, optionWriter: 0,
  writerLookupHit: 0, writerLookupMiss: 0,
  writerStatus1: 0, writerStatus2: 0, writerStatusOther: 0,
  optionLookup: 0, optionLookupHit: 0, optionLookupMiss: 0,
};

// The two strings the status writer compares, plus the pointers, so the failure
// arm is identifiable from the log instead of inferred. MSVC std::string:
// size at +0x10, capacity at +0x18, inline buffer at +0 when capacity <= 0xf.
const writerSamples = [];
let writerDepth = 0;

function readMsvcString(p) {
  try {
    const size = p.add(0x10).readU64().toNumber();
    const cap = p.add(0x18).readU64().toNumber();
    const data = cap > 0xf ? p.readPointer() : p;
    const n = Math.min(size, 96);
    const bytes = data.readByteArray(n);
    return Array.from(new Uint8Array(bytes))
      .map((b) => (b >= 32 && b < 127 ? String.fromCharCode(b) : '.')).join('');
  } catch (e) {
    return 'err:' + String(e).slice(0, 60);
  }
}
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

// CONTROL: FUN_145aa23f0 is the connection-wrapper tick (only while a REP
// connection exists); FUN_1416adce0 drains the deferred-action queue once per
// frame and FUN_145f62e80 is the per-frame view/camera update, so those two run
// from early on. If ALL THREE read 0 the probe is attached but inert.
hook(0x145aa23f0, 'frame-tick', () => { counters.frameTick++; });
hook(0x1416adce0, 'game-tick', () => { counters.gameTick++; });
hook(0x145f62e80, 'view-tick', () => { counters.viewTick++; });

// Boundary ladder between the socket and the bundle split: the typed-stream
// dispatch (10-GUID compare) and the main-thread ring drain.
hook(0x146b6f190, 'typed-dispatch', () => { counters.typedDispatch++; });
hook(0x146b6d180, 'ring-drain', () => { counters.ringDrain++; });

// Gate chain: the facet option apply, the status writer, and the local option
// lookup that decides whether the wire string is compared at all. The lookup
// returns an optional<std::string> whose 'has value' byte sits at out+0x40 in
// the caller's frame (FUN_146929df0: cStack_38).
hook(0x14683c8d0, 'facet-apply', () => { counters.facetApply++; });
Interceptor.attach(at(0x146929df0), {
  onEnter(args) {
    counters.optionWriter++;
    writerDepth++;
    this.state = args[0];
    if (writerSamples.length < 12) {
      const sample = { ev: 'option-writer', n: counters.optionWriter };
      try {
        const entity = args[1].sub(0x7d0);
        sample.entity = entity.toString();
        sample.slot7c0 = entity.add(0x7c0).readPointer().toString();
      } catch (e) {}
      sample.wire = readMsvcString(args[1]);    // entity+0x7d0
      sample.applied = readMsvcString(args[2]); // entity+0x880
      writerSamples.push(sample);
    }
  },
  onLeave() {
    writerDepth--;
    try {
      const st = this.state.add(0x318).readU32();
      if (st === 1) counters.writerStatus1++;
      else if (st === 2) counters.writerStatus2++;
      else counters.writerStatusOther++;
    } catch (e) {}
  }
});
// The local option lookup. Split the hit/miss count by whether the call comes
// from the status writer: a miss inside the writer is the "no local entry" arm.
Interceptor.attach(at(0x140fca4e0), {
  onEnter(args) {
    counters.optionLookup++;
    this.out = args[0];
    this.inWriter = writerDepth > 0;
  },
  onLeave() {
    let found = 0;
    try { found = this.out.add(0x40).readU8(); } catch (_) {}
    if (this.inWriter) {
      if (found) counters.writerLookupHit++; else counters.writerLookupMiss++;
      const last = writerSamples[writerSamples.length - 1];
      if (last && last.local === undefined) last.local = readMsvcString(this.out);
    } else if (found) {
      counters.optionLookupHit++;
    } else {
      counters.optionLookupMiss++;
    }
  }
});

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
    factoryByRecord: factoryByRecord, managerEvents: managerEvents,
    writerSamples: writerSamples });
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
