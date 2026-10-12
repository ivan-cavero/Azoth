#!/usr/bin/env python3
"""Read the local player's position the way the CLIENT ITSELF does.

WHY THIS EXISTS, AND WHY IT REPLACES THE OLD PROBE. The previous attempt
(`frida-movement-state.py`) diffed the bytes of the entity's `Transform` component and found
nothing, because that object's head is a pointer/counter header, not floats. Guessing the
offset was the wrong approach. This probe does not guess: it calls the client's OWN position
accessor, located from the client's own console command `nw_getPlayerPosition`
("print player position to the screen").

The chain, read from the binary (Steam exe 8654f01d, image base 0x140000000):

  * the console command `nw_getPlayerPosition` (name string 0x147fcfe50) is registered at
    0x1410352a1 inside the console-command table, with its handler at **0x141015b30**;
  * that handler calls **FUN_140fddfa0(&holder)** and then prints
    `*(float*)(holder+0x14c)`, `*(float*)(holder+0x15c)`, `*(float*)(holder+0x16c)`
    through `FUN_141022a90`. Those three floats ARE the local player position, in the
    client's own format.
  * the sibling command `teleport` (name 0x147fcf920, registered at 0x141034fb4) has its
    handler at 0x141020a40 and ultimately calls `FUN_140fbf3b0`, i.e. the client CAN set its
    own position locally.

So this probe calls the getter and reads the three floats. It also counts `FUN_141022a90`
so that a real `nw_getPlayerPosition` invocation can be cross-checked against the same
values, and it counts the delivery `FUN_143f97bf0` as the movement-message control.

READ-ONLY in the sense that matters: it invokes a getter the client calls itself for its own
console command, and reads memory. Nothing is written.

Usage:
  python az.py probe frida-player-position --timeout 600 --poll 0.25
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

GETTER = 0x140FDDFA0     # FUN_140fddfa0(&holder) - the client's own position accessor
PRINTER = 0x141022A90    # FUN_141022a90(&fmt, x, y, z) - what nw_getPlayerPosition prints with
DELIVER = 0x143F97BF0    # 4216 delivery (control: 0 when the position reply is off)
DISPATCH = 0x1416BCBA0   # RMI dispatch (control)

POS_OFFSETS = (0x14C, 0x15C, 0x16C)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const getter = new NativeFunction(rva(0x140fddfa0), 'pointer', ['pointer']);
  let prints = 0, delivers = 0, dispatches = 0;

  // Cross-check instrument: the client's own console command prints through this function.
  // Frida does not expose xmm registers, so this is a call counter only - enough to confirm
  // that a `nw_getPlayerPosition` invocation happened when one is triggered from the UI.
  try {
    Interceptor.attach(rva(0x141022a90), { onEnter() { prints++; } });
  } catch (e) { send({ ev: 'error', hook: 'printer', error: String(e) }); }

  try { Interceptor.attach(rva(0x143f97bf0), { onEnter() { delivers++; } }); } catch (e) {}
  try { Interceptor.attach(rva(0x1416bcba0), { onEnter() { dispatches++; } }); } catch (e) {}

  rpc.exports = {
    // Call the client's own getter and read the three floats it points at.
    position() {
      try {
        const out = Memory.alloc(0x18);
        out.writeByteArray(new Uint8Array(0x18));
        getter(out);
        const holder = out.readPointer();
        if (holder.isNull()) return { ok: false, reason: 'getter returned null holder' };
        const vals = [];
        for (const off of %OFFSETS%) {
          try { vals.push({ off: off, f: holder.add(off).readFloat() }); }
          catch (e) { vals.push({ off: off, err: String(e) }); }
        }
        return { ok: true, holder: holder.toString(), vals: vals,
                 prints: prints, delivers: delivers, dispatches: dispatches };
      } catch (e) { return { ok: false, reason: String(e) }; }
    },
    counters() { return { prints: prints, delivers: delivers, dispatches: dispatches }; },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--poll", type=float, default=0.25)
    ap.add_argument("--process", default="NewWorld.exe")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.process)
    script = session.create_script(
        JS.replace("%OFFSETS%", json.dumps(list(POS_OFFSETS)))
    )
    script.on("message", lambda m, d: print("[pp]", json.dumps(m), flush=True))
    script.load()
    print(f"[pp] attached to {args.process}", flush=True)

    capture = probe_capture(f"player-position-{int(time.time())}.jsonl")
    print(f"[pp] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    last_log = 0.0
    last_vals = None
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                st = script.exports_sync.position()
            except Exception as exc:  # noqa: BLE001
                print(f"[pp] status error: {exc}", flush=True)
                time.sleep(1.0)
                continue
            fh.write(json.dumps({"t": time.time(), **st}) + "\n")
            fh.flush()
            if st.get("ok"):
                vals = tuple(round(v.get("f", float("nan")), 4) for v in st["vals"])
                changed = last_vals is not None and vals != last_vals
                if changed or time.time() - last_log > 5:
                    flag = "  <-- CHANGED" if changed else ""
                    print(f"[pp] holder={st['holder']} pos={vals} "
                          f"prints={st['prints']} deliver={st['delivers']} "
                          f"dispatch={st['dispatches']}{flag}", flush=True)
                    last_log = time.time()
                last_vals = vals
            else:
                if time.time() - last_log > 5:
                    print(f"[pp] not available: {st.get('reason')}", flush=True)
                    last_log = time.time()
            time.sleep(args.poll)

    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    print(f"[pp] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
