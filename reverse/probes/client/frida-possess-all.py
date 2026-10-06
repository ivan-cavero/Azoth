#!/usr/bin/env python3
"""Try every valid id in the manager's table as the possessed local player.

The manager (`FUN_141026080`) owns a bucket table at `mgr+0x110` holding 13
real actors (vtable `nw+8033f90`) plus one stub. `FUN_146801040` resolves the
local player by looking up `[mgr+8]` in exactly that table and returning
`node+0x28`. The FSM gate (`FUN_146800d10`, vtable +0x30) returns `[mgr+8]`
only when `[mgr+0x10]` points at a non-zero byte.

Nothing ever writes that pair (measured: 28095 gate reads, entity 0, flag null;
no writer in .text; single instance). This script supplies it live:

  * allocates a persistent byte = 1 and points `[mgr+0x10]` at it
    (the earlier attempt crashed because the flag allocation had been freed);
  * writes each candidate id from the table into `[mgr+8]`, one at a time,
    and reports the gate's answer, so we can see which id (if any) makes the
    FSM advance.

In-memory only, private runtime only. Restore by restarting the game.

Usage:
  python reverse/probes/client/frida-possess-all.py  # use an interpreter with frida installed
  ... --id <decimal>     only try one id
  ... --hold             keep the last id written (do not advance)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import frida
from _paths import project_log

LOG = project_log("possess-all.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
const GATE = at(0x146800d10);

let mgr = null;
Interceptor.attach(GATE, {
  onEnter(args) { if (mgr === null) mgr = args[0]; }
});

// a flag byte that lives as long as this script does
const FLAG = Memory.alloc(16);
FLAG.writeU8(1);

function collect() {
  if (mgr === null) return null;
  const cells = mgr.add(0x110).readPointer();
  const n = Number(mgr.add(0x108).readU64()) + 1;
  const seen = new Set();
  const ids = [];
  for (let i = 0; i < n; i++) {
    let node = cells.add(i * 0x10).add(8).readPointer();
    let g = 0;
    while (!node.isNull() && g < 4096) {
      const k = node.toString();
      if (!seen.has(k)) {
        seen.add(k);
        const idv = node.add(0x10).readU64();
        const actor = node.add(0x28).readPointer();
        let ok = false;
        try {
          if (!actor.isNull()) {
            const v = actor.readPointer();
            ok = v.compare(base) >= 0 && v.compare(base.add(mod.size)) < 0;
          }
        } catch (e) {}
        if (ok) ids.push(idv.toString());
      }
      node = node.readPointer();
      g++;
    }
  }
  return ids;
}

function gateAnswer() {
  try {
    const ent = mgr.add(8).readPointer();
    const rp = mgr.add(0x10).readPointer();
    const flag = rp.isNull() ? null : rp.readU8();
    return { entity: ent.toString(), flagPtr: rp.toString(), flag: flag };
  } catch (e) { return { err: String(e) }; }
}

rpc.exports = {
  list() {
    return collect();
  },
  set(idStr) {
    if (mgr === null) return { err: 'no manager yet' };
    mgr.add(0x10).writePointer(FLAG);          // ready flag, persistent
    const id = ptr(idStr);
    mgr.add(8).writePointer(id);               // possessed entity key
    return gateAnswer();
  },
  clear() {
    if (mgr === null) return { err: 'no manager yet' };
    mgr.add(8).writePointer(ptr(0));
    mgr.add(0x10).writePointer(ptr(0));
    return gateAnswer();
  },
  peek() { return gateAnswer(); },
};
send({ ev: 'ready' });
"""


def main() -> int:
    only = None
    hold = "--hold" in sys.argv
    if "--id" in sys.argv:
        only = sys.argv[sys.argv.index("--id") + 1]

    logf = LOG.open("a", encoding="utf-8")
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)

    def on_msg(m, _d) -> None:
        p = m.get("payload")
        line = json.dumps(p) if isinstance(p, dict) else str(p)
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    script.on("message", on_msg)
    script.load()
    time.sleep(2)

    # wait for the gate to hand us the manager
    for _ in range(120):
        try:
            ids = script.exports_sync.list()
            if ids:
                break
        except Exception:
            ids = None
        time.sleep(1)

    if not ids:
        print("[possess-all] manager/table never appeared", flush=True)
        return 1
    print(f"[possess-all] manager found, {len(ids)} valid ids", flush=True)

    cands = [only] if only else ids
    for i, cid in enumerate(cands):
        ans = script.exports_sync.set(cid)
        print(f"  [{i + 1}/{len(cands)}] id={cid} -> {ans}", flush=True)
        time.sleep(1.5)

    if not hold and not only:
        print("[possess-all] leaving the LAST id in place", flush=True)
    print("[possess-all] done", flush=True)
    while True:
        time.sleep(5)
        print(f"  peek: {script.exports_sync.peek()}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
