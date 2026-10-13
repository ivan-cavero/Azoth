#!/usr/bin/env python3
"""Can the LIVE client actually move its own player? Reproduce the client's own
`teleport x y z` console command and measure the position before and after.

WHY THIS IS THE DECISIVE CHEAP TEST
===================================
Every measurement so far says the same thing: the client streams its input to the
server (20 channel-1 records/s, wire `0x635`), and the local transform does not move
at all. That leaves two very different worlds, and nothing measured yet separates
them:

  A. the position state is live and writable, and movement is blocked specifically at
     the input/action layer (the ALC conversation whose timeout is the red HUD cable); or
  B. the local-control path is not wired up at all, and we are missing far more than
     one input response.

This probe separates them using the client's OWN debug command. In `teleport`'s
handler (`FUN_141020a40`):

    iVar4 = (*(*args + 8))(args);              // IConsoleCmdArgs::GetArgCount()
    if (iVar4 == 4) {                          // "teleport <x> <y> <z>"
      x = atof((*(*args + 0x10))(args, 1));    // GetArg(1)
      y = atof((*(*args + 0x10))(args, 2));
      z = atof((*(*args + 0x10))(args, 3));
      FUN_140fbf3b0(&{fn, 0}, &vec3);          // 0x14057148c thunk, 3 floats
    }

`FUN_140fbf3b0` is a generic dispatcher: for each entity in a manager list it calls
`fn(entity + offset, &vec3)`. Its only callers are the two branches of that handler
plus two later sites, so calling it this way is the client's own code path, not an
invention. `0x14057148c` is a virtual-call thunk (`mov rax,[rcx]; jmp [rax+0x18]`).

THIS MUTATES GAME STATE. It is not read-only: it moves the local player. That is the
point — but say so in the capture, and do not run it on a session whose position
matters.

Also reports the control: the position is read again with the client's own accessor
(`FUN_140fddfa0`, floats at +0x14c/+0x15c/+0x16c), the same instrument validated in
`frida-player-position.py`.

Usage:
  python az.py probe frida-teleport-test --target 9400,2800,90 --shutdown kill
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

DISPATCH = 0x140FBF3B0  # FUN_140fbf3b0(&{fn,0}, &vec3) - per-entity dispatcher
SETTER_THUNK = 0x14057148C  # the per-entity virtual setter the command uses
GETTER = 0x140FDDFA0  # the validated position accessor
POS_OFFSETS = (0x14C, 0x15C, 0x16C)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const getter = new NativeFunction(rva(0x140fddfa0), 'pointer', ['pointer']);
  const dispatch = new NativeFunction(rva(0x140fbf3b0), 'void', ['pointer', 'pointer']);

  function readPos() {
    try {
      const out = Memory.alloc(0x18);
      out.writeByteArray(new Uint8Array(0x18));
      getter(out);
      const holder = out.readPointer();
      if (holder.isNull()) return { ok: false, reason: 'null holder' };
      const v = [];
      for (const off of %OFFSETS%) {
        try { v.push(holder.add(off).readFloat()); } catch (e) { v.push(null); }
      }
      return { ok: true, holder: holder.toString(), pos: v };
    } catch (e) { return { ok: false, reason: String(e) }; }
  }

  let cbKeepAlive = null;   // a NativeCallback must not be collected while in use

  rpc.exports = {
    read() { return readPos(); },
    // Reproduce `teleport x y z`: a 16-byte {fn, 0} holder plus a 12-byte vec3, both
    // handed to the client's own dispatcher.
    teleport(x, y, z) {
      try {
        const holder = Memory.alloc(16);
        holder.writePointer(rva(0x14057148c));
        holder.add(8).writePointer(ptr(0));
        const vec = Memory.alloc(16);
        vec.writeFloat(x);
        vec.add(4).writeFloat(y);
        vec.add(8).writeFloat(z);
        dispatch(holder, vec);
        return { ok: true, raw: { holder: holder.toString(), vec: vec.toString() } };
      } catch (e) { return { ok: false, reason: String(e) }; }
    },
    // DISCRIMINATOR: run the same dispatcher with OUR callback as `fn`. The count says
    // whether the dispatcher visited ANY entity at all. If it visits zero, the command
    // is a no-op for this client state and 'teleport did not move the player' says
    // nothing about whether the client can move it; if it visits some, the callback
    // gets the per-entity object pointer, which is the thing to compare with the
    // entity the component list belongs to.
    probeDispatch() {
      let count = 0;
      const seen = [];
      cbKeepAlive = new NativeCallback(function (obj, vec) {
        count++;
        if (seen.length < 8) {
          let v = null;
          try { v = [vec.readFloat(), vec.add(4).readFloat(), vec.add(8).readFloat()]; }
          catch (e) { v = String(e); }
          const row = { obj: obj.toString(), vec: v };
          // Identify the visited object: its vtable, the pointer the dispatcher will
          // hand the setter (this object + 0x28 in the decompiled loop is plVar8[5]),
          // and the AZ type GUID if slot 0 behaves as the type getter.
          try { row.vtable = obj.readPointer().toString(); } catch (e) { row.vtable = null; }
          try { row.at_28 = obj.add(0x28).readPointer().toString(); } catch (e) { row.at_28 = null; }
          try {
            const vt = obj.readPointer();
            const fn = vt.readPointer();
            const tp = new NativeFunction(fn, 'pointer', ['pointer'])(obj);
            if (!tp.isNull()) {
              const b = new Uint8Array(tp.readByteArray(16));
              const h = Array.from(b).map((x) => ('0' + x.toString(16)).slice(-2)).join('');
              row.guid = (h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' +
                          h.slice(16, 20) + '-' + h.slice(20)).toUpperCase();
            }
          } catch (e) { row.guid = null; }
          seen.push(row);
        }
      }, 'void', ['pointer', 'pointer']);
      try {
        const holder = Memory.alloc(16);
        holder.writePointer(cbKeepAlive);
        holder.add(8).writePointer(ptr(0));
        const vec = Memory.alloc(16);
        vec.writeFloat(1);
        vec.add(4).writeFloat(2);
        vec.add(8).writeFloat(3);
        dispatch(holder, vec);
        return { ok: true, visited: count, seen: seen };
      } catch (e) { return { ok: false, reason: String(e), visited: count }; }
    },
    teardown() { try { Interceptor.detachAll(); return true; } catch (e) { return String(e); } },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="9400,2800,90",
                    help="x,y,z to teleport to (default is +~56 east of spawn)")
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--probe-dispatch", action="store_true",
                    help="also run the dispatcher with our own callback to count how many "
                         "entities it visits (discriminates 'no-op' from 'wrong object')")
    ap.add_argument("--shutdown", choices=["kill", "detach"], default="kill",
                    help="kill (default) ends the client deliberately; detach tries an "
                         "orderly teardown of the agent")
    args = ap.parse_args()

    try:
        x, y, z = (float(v) for v in args.target.split(","))
    except ValueError:
        print(f"bad --target {args.target!r}; want x,y,z")
        return 2

    device = frida.get_local_device()
    session = device.attach(args.process)
    pid = session.pid
    script = session.create_script(JS.replace("%OFFSETS%", json.dumps(list(POS_OFFSETS))))
    script.on("message", lambda m, d: print("[tp]", json.dumps(m), flush=True))
    script.load()
    print(f"[tp] attached to {args.process} pid={pid}", flush=True)

    capture = probe_capture(f"teleport-test-{int(time.time())}.jsonl")
    print(f"[tp] live -> {capture}", flush=True)

    before = script.exports_sync.read()
    print(f"[tp] BEFORE {json.dumps(before)}", flush=True)
    result = script.exports_sync.teleport(x, y, z)
    print(f"[tp] teleport({x},{y},{z}) -> {json.dumps(result)}", flush=True)
    time.sleep(args.settle)
    after = script.exports_sync.read()
    print(f"[tp] AFTER  {json.dumps(after)}", flush=True)

    moved = False
    if before.get("ok") and after.get("ok"):
        moved = before["pos"] != after["pos"]
        print(f"[tp] MOVED = {moved}", flush=True)
        if moved:
            print(f"[tp]   delta = {[round(b - a, 3) for a, b in zip(before['pos'], after['pos'])]}",
                  flush=True)

    visited = None
    if args.probe_dispatch:
        visited = script.exports_sync.probe_dispatch()
        print(f"[tp] DISPATCH VISITS = {json.dumps(visited)}", flush=True)

    with capture.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.time(), "requested": [x, y, z], "before": before,
                             "call": result, "after": after, "moved": moved,
                             "visits": visited}) + "\n")
        fh.flush()

    strategy = safe_shutdown(session, script, kill=(args.shutdown == "kill"), device=device,
                             log=lambda m: print(f"[tp] {m}", flush=True))
    print(f"[tp] shutdown strategy: {strategy}", flush=True)
    print(f"[tp] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
