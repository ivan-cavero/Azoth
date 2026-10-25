#!/usr/bin/env python3
"""Run the client's OWN `teleport x y z` command by handing its handler a real-looking
`IConsoleCmdArgs`. This is the decisive test of whether the client can move its player.

WHY THIS IS DIFFERENT FROM `frida-teleport-test.py`
==================================================
That probe called the dispatcher `FUN_140fbf3b0` directly and the player did not move, but the
call had two confounds: it was made from a Frida thread rather than the client's own console
path, and the object the dispatcher visited was never identified (it was not an AZ-reflected
component). This probe removes both by driving the client's actual command handler.

The handler `FUN_141020a40` is pure virtual dispatch on its argument:

    iVar4 = (*(*args + 8))(args);                  // IConsoleCmdArgs::GetArgCount()
    if (iVar4 == 4) {                              // "teleport <x> <y> <z>"
      x = atof((*(*args + 0x10))(args, 1));        // GetArg(1) -> const char*
      y = atof((*(*args + 0x10))(args, 2));
      z = atof((*(*args + 0x10))(args, 3));
      FUN_140fbf3b0(&{thunk, 0}, &vec3);           // the per-entity write
    }

So the handler needs nothing but an object whose first word is a vtable with a function at +8
and another at +0x10. Building that is exact, not a guess: two `NativeCallback`s returning the
arg count and a C string per index.

WHAT THE OUTCOME MEANS
======================
* Player MOVES  -> the client CAN move its own player, so the blocker is a client-side gate on
  the normal input path (the ALC conversation), not missing server state. That reframes the
  movement work entirely.
* Player does NOT move -> the write path itself is inert for this entity, which supports the
  reading that the position is purely server-authoritative and our server must send it.

Either answer is a real result. This MUTATES game state on success (it moves the player), so it
is not read-only; say so when quoting the capture.

Usage:
  python ef.py probe frida-teleport-handler --target 9400,2800,90
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

HANDLER = 0x141020A40  # the `teleport` console command handler
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
  const handler = new NativeFunction(rva(0x141020a40), 'void', ['pointer']);

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

  // Keep the callbacks and the strings alive for the whole call: a NativeCallback that is
  // collected while the target still holds it is a crash, and the same is true of the strings.
  let keep = [];

  rpc.exports = {
    read() { return readPos(); },
    teleport(x, y, z) {
      try {
        const argv = ['teleport', String(x), String(y), String(z)];
        const ptrs = [];
        for (const s of argv) {
          const buf = Memory.allocUtf8String(s);
          keep.push(buf);
          ptrs.push(buf);
        }
        const getArgCount = new NativeCallback(function () { return argv.length; },
                                               'int', ['pointer']);
        const getArg = new NativeCallback(function (self, i) {
          if (i < 0 || i >= ptrs.length) return ptr(0);
          return ptrs[i];
        }, 'pointer', ['pointer', 'int']);
        keep.push(getArgCount, getArg);

        const vt = Memory.alloc(0x20);
        vt.add(8).writePointer(getArgCount);
        vt.add(0x10).writePointer(getArg);
        const args = Memory.alloc(0x10);
        args.writePointer(vt);
        keep.push(vt, args);

        handler(args);
        return { ok: true, argv: argv, vt: vt.toString(), args: args.toString() };
      } catch (e) { return { ok: false, reason: String(e) }; }
    },
    teardown() { try { Interceptor.detachAll(); return true; } catch (e) { return String(e); } },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="9400,2800,90")
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--shutdown", choices=["kill", "detach"], default="kill")
    args = ap.parse_args()

    x, y, z = (float(v) for v in args.target.split(","))

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS.replace("%OFFSETS%", json.dumps(list(POS_OFFSETS))))
    script.on("message", lambda m, d: print("[th]", json.dumps(m), flush=True))
    script.load()
    print(f"[th] attached to {args.process}", flush=True)

    capture = probe_capture(f"teleport-handler-{int(time.time())}.jsonl")
    print(f"[th] live -> {capture}", flush=True)

    before = script.exports_sync.read()
    print(f"[th] BEFORE {json.dumps(before)}", flush=True)
    call = script.exports_sync.teleport(x, y, z)
    print(f"[th] handler({x},{y},{z}) -> {json.dumps(call)}", flush=True)
    time.sleep(args.settle)
    after = script.exports_sync.read()
    print(f"[th] AFTER  {json.dumps(after)}", flush=True)

    moved = False
    if before.get("ok") and after.get("ok"):
        moved = before["pos"] != after["pos"]
        print(f"[th] MOVED = {moved}", flush=True)
        if moved:
            print(f"[th]   delta = {[round(b - a, 3) for a, b in zip(before['pos'], after['pos'])]}",
                  flush=True)

    with capture.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.time(), "requested": [x, y, z], "before": before,
                             "call": call, "after": after, "moved": moved}) + "\n")
        fh.flush()

    strategy = safe_shutdown(session, script, kill=(args.shutdown == "kill"), device=device,
                             log=lambda m: print(f"[th] {m}", flush=True))
    print(f"[th] shutdown strategy: {strategy}", flush=True)
    print(f"[th] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
