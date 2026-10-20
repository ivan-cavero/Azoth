#!/usr/bin/env python3
"""Identify the object that holds the local player's position, and its type.

WHY THIS EXISTS, and it is where the evidence points after 2026-10-20. Three attempts to find a
world position inside an entity's `Transform` or `AsyncRenderTransformComponent` failed, and the
control that settles it is the LOCAL PLAYER: it certainly renders, and it has no such position in
either component. So the position lives somewhere else. It is known to be reachable through the
client's own accessor: `FUN_140fddfa0(&out)` fills a three-pointer structure whose first element is
an object, and the `nw_getPlayerPosition` handler reads `*(float*)(that + 0x14c / +0x15c / +0x16c)`.

The decompiled accessor (`FUN_140fddfa0`) shows the object comes from `FUN_140fdd9b0`, not from the
entity's component list - a different path. This probe answers, at runtime and read-only:

  1. what the accessor returns, and whether `+0x14c/+0x15c/+0x16c` really are the position
     (compared against the server's own authoritative position, which the world log prints);
  2. the object's VTABLE and its AZ TYPE GUID, read by calling vtable slot 0 exactly as the component
     namer does - so the answer is the client's own type id, not a guess from the code shape;
  3. whether that type is a component the client can also resolve on OTHER entities, which is what
     would make a remote body's position reachable.

Read-only: it calls an existing accessor and reads memory. It writes nothing.

NO UNLOAD AT THE END: `frida-agent.dll_unloaded` execute-after-unload is a measured crash source here
(offset 0x9c7e0, reproduced many times). Leave it attached; end the client with `python az.py stop`.

Usage:
  python az.py probe frida-position-holder
"""

from __future__ import annotations

import json
import time

import frida

ACCESSOR = 0x140FDDFA0  # FUN_140fddfa0(longlong *out) - fills a 3-pointer structure
POSITION_OFFSETS = (0x14C, 0x15C, 0x16C)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => base.add(v - 0x140000000);
const codeRanges = mod.enumerateRanges('r-x');

function inCode(p) {
  for (let i = 0; i < codeRanges.length; i++) {
    const r = codeRanges[i];
    if (p.compare(r.base) >= 0 && p.compare(r.base.add(r.size)) < 0) return true;
  }
  return false;
}

function guidOf(p) {
  try {
    const b = new Uint8Array(p.readByteArray(16));
    const h = Array.from(b).map((x) => x.toString(16).padStart(2, '0')).join('');
    return (h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' +
            h.slice(16, 20) + '-' + h.slice(20)).toUpperCase();
  } catch (e) { return null; }
}

const accessor = new NativeFunction(rva(0x140fddfa0), 'void', ['pointer']);
const out = Memory.alloc(0x40);

function report() {
  const rec = { ev: 'holder' };
  try {
    // Poison the buffer so a field the accessor does not write cannot be mistaken for a value.
    for (let i = 0; i < 0x40; i += 8) out.add(i).writeU64(uint64('0xffffffffffffffff'));
    accessor(out);
    const h0 = out.readPointer();
    rec.out = [h0.toString(), out.add(8).readPointer().toString(), out.add(0x10).readPointer().toString()];
    if (h0.isNull()) { send(rec); return; }

    rec.pos = [];
    for (const off of [0x14c, 0x15c, 0x16c]) rec.pos.push(+h0.add(off).readFloat().toFixed(4));

    // The object's own identity: vtable, then the AZ type GUID through vtable slot 0.
    try {
      const vt = h0.readPointer();
      rec.vtable = vt.toString();
      rec.vtableInCode = inCode(vt);
      const slot0 = vt.readPointer();
      rec.slot0 = slot0.toString();
      rec.slot0InCode = inCode(slot0);
      if (inCode(slot0)) {
        const fn = new NativeFunction(slot0, 'pointer', ['pointer']);
        const t = fn(h0);
        if (!t.isNull()) rec.typeGuid = guidOf(t);
      }
    } catch (e) { rec.vtableError = String(e).slice(0, 90); }

    // A short hexdump, so an offline pass can look for the triple without another run.
    try {
      const b = h0.readByteArray(0x200);
      if (b !== null) {
        const u8 = new Uint8Array(b); let s = '';
        for (let i = 0; i < u8.length; i++) s += u8[i].toString(16).padStart(2, '0');
        rec.head = s;
      }
    } catch (e) { }
  } catch (e) { rec.fatal = String(e).slice(0, 120); }
  send(rec);
}

// THE ACCESSOR MUST RUN ON THE GAME THREAD. Called from a Frida interval thread it returns an
// all-zero structure (measured: out=['0x0','0x0','0x0'] on a fully loaded world), which is what a
// per-thread context getter looks like. So the call is made from INSIDE a hook on a function the
// game calls constantly, which runs on its own thread with its own context.
let hookCount = 0;
Interceptor.attach(rva(0x1413fb700), {
  onEnter(args) {
    hookCount++;
    if (hookCount % 20000 === 0) report();
  },
});
send({ ev: 'probe-ready' });
"""


def main() -> int:
    device = frida.get_local_device()
    pid = next((p.pid for p in device.enumerate_processes()
                if p.name.lower() == "newworld.exe"), None)
    if pid is None:
        print("[holder] no NewWorld.exe running")
        return 1

    session = device.attach(pid)
    script = session.create_script(JS)
    latest: dict = {}
    count = 0

    def on_message(message, _data):
        nonlocal count
        if message.get("type") != "send":
            print("[holder] err:", str(message.get("description"))[:200], flush=True)
            return
        payload = message["payload"]
        if payload.get("ev") != "holder":
            return
        count += 1
        latest.clear()
        latest.update(payload)
        if count <= 3:
            print(f"[holder] #{count} out={payload.get('out')} pos={payload.get('pos')} "
                  f"vtable={payload.get('vtable')} inCode={payload.get('vtableInCode')} "
                  f"type={payload.get('typeGuid')}", flush=True)
        try:
            with open(".azoth/state/position-holder.json", "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except OSError:
            pass

    script.on("message", on_message)
    script.load()
    print(f"[holder] attached pid={pid}; sampling until stopped", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
