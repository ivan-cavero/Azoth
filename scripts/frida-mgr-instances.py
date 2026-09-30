#!/usr/bin/env python3
"""How many local-player manager instances exist, and on which threads?

WHY (static finding 2026-09-30). The manager `FUN_141026080` is a *per-thread*
(TLS) singleton: its one-time init stores `_DAT_14a2fb9f0 =
FUN_141676530(FUN_147aad091(0x14a13c610, 0x14a829d20))` (an FNV-1a name->storage
registry lookup) and every call then reads `*_DAT_14a2fb9f0`; when that is 0 it
calls `FUN_1416ad7e0`, which reads `gs:[0x58]` (Windows TLS). So the address of
the object handed back depends on the calling thread.

That matters because THREE static scans over `.text` found no writer of
`[mgr+8]`/`[mgr+0x10]` other than the constructor `FUN_146713f00`, which merely
zeroes them. Two explanations remain:

  (a) the bind writes to a DIFFERENT thread's instance than the one the FSM
      gate (`FUN_146800d10`, vtable +0x30) reads -> the session is per-thread
      split and the earlier page-watch (which pinned ONE address) saw 0 writes;
  (b) the bind never runs at all -> the "no writer" problem is real.

This probe separates them. It hooks the singleton getter and reports every
distinct returned pointer together with the thread that got it, plus which
instance and which thread the FSM gate actually reads.

Read-only: no writes, no patches. Attach AFTER the game window exists, BEFORE
entering the world (or at any time; it is a pure observer). Run with the
Windows python (it has frida 17):

  "C:/Users/ivang/AppData/Local/Python/bin/python.exe" scripts/frida-mgr-instances.py

Writes JSON lines to stdout and to
%LOCALAPPDATA%/Temp/azoth-mgr-instances.log.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import frida

LOG = Path(r"C:\Users\ivang\AppData\Local\Temp\azoth-mgr-instances.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

// FUN_141026080  lazy per-thread singleton accessor -> returns the manager (or 0)
const SINGLETON = at(0x141026080);
// FUN_1416ad7e0  the per-thread creator, called when the storage holds 0
const CREATOR = at(0x1416ad7e0);
// FUN_146800d10  vtable+0x30 = the FSM gate getter: reads [rcx+8], [rcx+0x10]
const GETTER = at(0x146800d10);

const off = (p) => {
  try {
    if (p.isNull()) return 'null';
    const d = p.sub(base);
    if (d.compare(ptr(0)) < 0 || d.compare(ptr(mod.size)) >= 0) return p.toString();
    return 'nw+' + d.toString(16);
  } catch (e) { return '?'; }
};

// Every distinct pointer the singleton ever hands out, and who got it.
const instances = {};   // ptrString -> { off, tidFirst, calls, tids: {tid: count} }
// Every distinct object the FSM gate reads, and on which threads.
const gated = {};       // ptrString -> { off, calls, tids: {tid: count}, lastEntity, lastFlag }

function bump(map, ptrStr, tid, extra) {
  let r = map[ptrStr];
  if (!r) {
    r = map[ptrStr] = {
      off: extra && extra.off, tidFirst: tid, calls: 0, tids: {},
    };
    return { rec: r, fresh: true };
  }
  return { rec: r, fresh: false };
}

Interceptor.attach(SINGLETON, {
  onEnter(args) { this.tid = Process.getCurrentThreadId(); },
  onLeave(ret) {
    const p = ret;
    const key = p.toString();
    let r = instances[key];
    let fresh = false;
    if (!r) {
      r = instances[key] = { off: off(p), tidFirst: this.tid, calls: 0, tids: {} };
      fresh = true;
    }
    r.calls++;
    r.tids[this.tid] = (r.tids[this.tid] || 0) + 1;
    if (fresh) {
      send({ ev: 'instance-first', ptr: key, off: r.off, tid: this.tid });
    }
  }
});

Interceptor.attach(CREATOR, {
  onEnter(args) {
    send({ ev: 'creator-called', tid: Process.getCurrentThreadId(),
           arg: args[0] ? args[0].toString() : null });
  }
});

Interceptor.attach(GETTER, {
  onEnter(args) {
    const self = args[0];
    const key = self.toString();
    const tid = Process.getCurrentThreadId();
    let r = gated[key];
    if (!r) {
      r = gated[key] = { off: off(self), calls: 0, tids: {},
                         lastEntity: null, lastFlag: null };
    }
    r.calls++;
    r.tids[tid] = (r.tids[tid] || 0) + 1;
    try {
      const ent = self.add(8).readPointer();
      const rp = self.add(0x10).readPointer();
      r.lastEntity = ent.toString();
      r.lastFlag = rp.isNull() ? null : rp.readU8();
    } catch (e) { r.lastFlag = 'err'; }
  }
});

function snap() {
  const inst = Object.keys(instances).map((k) => ({
    ptr: k, off: instances[k].off, calls: instances[k].calls,
    nth: Object.keys(instances[k].tids).length, tids: instances[k].tids,
  }));
  const gate = Object.keys(gated).map((k) => ({
    ptr: k, off: gated[k].off, calls: gated[k].calls,
    nth: Object.keys(gated[k].tids).length, tids: gated[k].tids,
    entity: gated[k].lastEntity, flag: gated[k].lastFlag,
  }));
  send({
    ev: 'tick',
    distinct_instances: inst.length,
    distinct_gated: gate.length,
    instances: inst,
    gated: gate,
  });
}

setInterval(snap, 5000);
send({ ev: 'probe-ready' });
"""


def main() -> int:
    logf = LOG.open("a", encoding="utf-8")
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
    print("[mgr-instances] observing FUN_141026080 (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
