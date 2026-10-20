#!/usr/bin/env python3
"""Measure the remote-entity Transform gap, and optionally close it under a hard cap.

WHY. Every session logs `Slice: Couldn't get Transform component on the slice!` for
`slices/remoteplayer.dynamicslice` - 26 times in one clean session, 5 s after spawn, with the
server's NPC feature DISABLED. That slice is the one whose instance carries every entity's actor
id, so the entities the client clones for remote players and creatures end up with a NULL
Transform slot and therefore no world matrix: they exist in the client's tables but cannot be
placed in the scene. That is the leading explanation for "the created entity has a slot but no
body", and it also blocks the second-player item, because a remote player is one of these
instances.

WHAT THIS PROBE DOES
====================
Both call sites the atlas records are byte-verified here before anything is hooked:

    FUN_1416797d0  call @ 0x141679a5c -> 0x1413fb700 ; return 0x141679a61 (`mov r12,rax; test rax,rax; je`)
    FUN_1417880b0  call @ 0x1417882cc -> 0x1413fb700 ; return 0x1417882d1 (`mov r15,rax; test rax,rax; je`)

`FUN_1413fb700` is the component lookup, so the RETURN SITE is where the null is decided. The probe
hooks both returns and reports, per call, whether the lookup produced a component and which slice
the entity belongs to (read from the std::string at entity/+0x110 with the +0x120 size and +0x128
capacity, as recorded in `gametransform_attach_ab`).

MODES
=====
`--mode measure` (DEFAULT, and the only mode that is safe to run first)
    Counts null lookups, grouped by slice name. Read-only. This answers "is the remoteplayer gap
    real and how big is it" without touching client state.

`--mode attach` (OPT-IN, and the reason the cap is not optional)
    For a null lookup whose slice name contains `remoteplayer` and whose entity state byte
    (`entity+0x60`) is 0 or 2, calls the GameTransform factory `FUN_14169a210` and then
    `FUN_1413789c0` (AZ::Entity::AddComponent) to install it. **The cap defaults to 40 and must not
    be removed**: the 2026-10-03 A/B ran this unfiltered, performed 12488 attaches, stalled the
    game thread and the client left InGame with a connection failure. The factory is also called
    with no arguments and returns a default-constructed transform, which may be an identity matrix -
    so a body appearing is the acceptance signal, NOT the absence of warnings.

Read-only by default; `--mode attach` mutates client state and is the caller's explicit choice.
Ends through `device.kill` (this hooks hot code; a bare detach is the measured execute-after-unload
crash).

Usage:
  python az.py probe frida-remote-transform --mode measure --timeout 180
  python az.py probe frida-remote-transform --mode attach --cap 40 --timeout 180
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

LOOKUP = 0x1413FB700
RETURN_SITES = {
    0x141679A61: "FUN_1416797d0",
    0x1417882D1: "FUN_1417880b0",
}
FACTORY = 0x14169A210   # GameTransform factory, no-arg
ADD_COMPONENT = 0x1413789C0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const mode = %MODE%;
  const cap = %CAP%;

  const factory = new NativeFunction(rva(%FACTORY%), 'pointer', []);
  const addComp = new NativeFunction(rva(%ADD_COMPONENT%), 'void', ['pointer', 'pointer']);

  let currentEntity = null;
  let attached = 0;
  let nulls = 0;
  let hits = 0;
  const bySlice = {};

  // Read the entity's slice path: std::string at +0x110, size +0x120, capacity +0x128.
  function sliceName(entity) {
    try {
      const size = entity.add(0x120).readU32();
      const cap = entity.add(0x128).readU32();
      if (size === 0 || size > 260) return null;
      const ptr = cap > 15 ? entity.add(0x110).readPointer() : entity.add(0x110);
      return ptr.readUtf8String(size);
    } catch (e) { return null; }
  }

  // THESE ARE RETURN SITES, NOT FUNCTION ENTRIES, so the hook must be onEnter.
  //
  // MEASURED 2026-10-19: the first version of this probe used onLeave at these addresses and reported
  // `hits=0` on a session that logged the warning 26 times. That was an instrument bug, not a result:
  // Frida's onLeave fires when the function that STARTS at the attached address returns, and a
  // mid-function address never returns in that sense. At a return site the result is already in rax
  // when execution ARRIVES, so onEnter is the correct hook - and the bytes there are
  // `4c 8b e0 / 48 85 c0 / 0f 84` (mov r12,rax; test rax,rax; je), i.e. rax is exactly what the
  // client is about to test for null.
  const sites = %SITES%;
  for (const [retAddr, label] of sites) {
    try {
      Interceptor.attach(rva(retAddr), {
        onEnter() {
          hits++;
          let comp = null;
          try { comp = this.context.rax; } catch (e) {}
          const isNull = (comp === null || comp.isNull());
          if (isNull) nulls++;
          // The entity is not in a known register here, so the slice name is reported only when a
          // caller has set `currentEntity`; the null COUNT is the measurement that matters and it
          // does not depend on it.
          const name = currentEntity ? (sliceName(currentEntity) || '(unreadable)') : '(entity unknown)';
          bySlice[label + ' -> ' + name] = (bySlice[label + ' -> ' + name] || 0) + 1;
          if (mode === 'attach' && isNull && currentEntity && attached < cap) {
            const nm = sliceName(currentEntity) || '';
            if (nm.indexOf('remoteplayer') >= 0) {
              let state = -1;
              try { state = currentEntity.add(0x60).readU8() & 0xff; } catch (e) {}
              if (state === 0 || state === 2) {
                try {
                  const t = factory();
                  if (t && !t.isNull()) { addComp(currentEntity, t); attached++; }
                } catch (e) {}
              }
            }
          }
        }
      });
    } catch (e) {
      send({ ev: 'attach-error', label: label, error: String(e) });
    }
  }

  send({ ev: 'ready', base: base.toString(16), mode: mode, cap: cap });

  setInterval(() => {
    send({ ev: 'stats', hits: hits, nulls: nulls, attached: attached, bySlice: bySlice });
  }, 5000);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("measure", "attach"), default="measure")
    ap.add_argument("--cap", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to wait for a NewWorld.exe to appear (use when the client "
                         "is about to be launched by another script)")
    ap.add_argument("--pid", type=int, default=0,
                    help="attach to this pid instead of discovering one")
    args = ap.parse_args()

    sites = [[va, label] for va, label in RETURN_SITES.items()]
    source = (JS.replace("%MODE%", json.dumps(args.mode))
                .replace("%CAP%", str(args.cap))
                .replace("%FACTORY%", hex(FACTORY))
                .replace("%ADD_COMPONENT%", hex(ADD_COMPONENT))
                .replace("%SITES%", json.dumps(sites)))

    device = frida.get_local_device()

    def discover() -> int | None:
        if args.pid:
            return args.pid
        return next((p.pid for p in device.enumerate_processes()
                     if p.name.lower() == "newworld.exe"), None)

    pid = discover()
    if pid is None and args.wait:
        # THE HOOK MUST BE IN PLACE BEFORE THE WORLD LOADS. The lookups this probe measures
        # happen once, ~5 s after spawn, and an attach 2 minutes later measured 0 hits.
        deadline = time.time() + args.wait
        while pid is None and time.time() < deadline:
            time.sleep(1)
            pid = discover()
    if pid is None:
        print("[transform] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    out = probe_capture(f"remote-transform-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")
    last: dict = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[transform] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        fh.write(json.dumps(p) + "\n")
        fh.flush()
        if p.get("ev") == "ready":
            print(f"[transform] {p['mode']} cap={p['cap']} base={p['base']}", flush=True)
        elif p.get("ev") == "stats":
            last.update(p)
            print(f"[transform] hits={p['hits']} nulls={p['nulls']} "
                  f"attached={p['attached']} slices={json.dumps(p['bySlice'])[:300]}",
                  flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[transform] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    fh.close()
    print()
    print("  FINAL:", json.dumps(last.get("bySlice", {}), indent=1))
    print(f"  hits={last.get('hits')} nulls={last.get('nulls')} attached={last.get('attached')}")
    if args.mode == "measure":
        print("\n  Read-only. A null count concentrated on remoteplayer.dynamicslice is the gap;")
        print("  the next step is --mode attach, which mutates client state and is capped.")
    try:
        script.unload()
    except Exception:
        pass
    try:
        device.kill(pid)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
