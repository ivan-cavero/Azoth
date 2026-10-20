"""Hook the component LOOKUP itself, so the entity is available and a null can be repaired.

WHY THIS REPLACES HOOKING THE RETURN SITES
==========================================
Hooking the two return sites measured the gap correctly (`hits=14965, nulls=26`, exactly matching the
26 `Couldn't get Transform component on the slice!` lines in Game.log) but **could not repair it**: at a
return site the entity is a stack local, not a register, so there is nothing to pass to AddComponent.

`FUN_1413fb700` is the component lookup the warning is decided by, and its FIRST ARGUMENT IS THE
ENTITY. Hooking its entry and exit gives both halves of the fact in one place:

    onEnter : args[0] = entity, args[1] = the component type GUID being asked for
    onLeave : retval  = the component, or null

So this probe can say, per lookup, WHICH component was missing on WHICH entity, and can repair exactly
the ones that matter instead of guessing.

THE REPAIR IS OFF BY DEFAULT AND CAPPED WHEN ON
===============================================
`--mode attach` installs a GameTransform on entities whose lookup for the GameTransform type id came
back null. **The cap defaults to 40 and must not be removed**: the 2026-10-03 A/B ran an unfiltered
version of this, performed 12488 attaches, stalled the game thread, and the client left InGame with a
connection failure. The factory is no-argument and returns a default-constructed transform, which may
be an identity matrix, so **a body appearing is the acceptance signal - not the absence of warnings**.

Usage:
  python az.py probe frida-transform-lookup --mode measure --wait 400 --timeout 300
  python az.py probe frida-transform-lookup --mode attach --cap 40 --wait 400 --timeout 300
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

LOOKUP = 0x1413FB700
FACTORY = 0x14169A210
ADD_COMPONENT = 0x1413789C0
# {484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0} - the entity-component Transform (NOT the AZ math struct,
# which is {5D9958E9-...}; pairing the wrong one is a documented trap).
TRANSFORM_GUID_LE = bytes.fromhex("7DE64A48D0AB9C4DB2C89BB0EEC900E0").hex()

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const mode = %MODE%;
  const cap = %CAP%;

  const factory = new NativeFunction(rva(%FACTORY%), 'pointer', []);
  const addComp = new NativeFunction(rva(%ADD_COMPONENT%), 'void', ['pointer', 'pointer']);

  let calls = 0, transformLookups = 0, transformNulls = 0, attached = 0;
  // MEASURED 2026-10-19 from the null-lookup census: the type id that comes back NULL on the
  // remoteplayer entities is 484ae67dabd04d9cb2c89bb0eec900e0, which is exactly
  // {484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0} = GameTransformComponent. 116 nulls in one session.
  // The lazy 'first type that nulls' heuristic picked 50b8cf6c... instead (75281 nulls), so the
  // id is pinned here as measured protocol data.
  let transformHex = '484ae67dabd04d9cb2c89bb0eec900e0';
  const missing = {};
  const nullByType = {};

  // SIGNATURE, read from the disassembly rather than assumed.
  //
  //   FUN_1413fb700(arg0 = ENTITY, arg1 = POINTER TO THE 16-BYTE TYPE ID)
  //
  // The lookup body is `r14 = rdx; ...; cmp qword ptr [rcx], rax` / `mov rax,[r14+8]`, i.e. it
  // compares the 16-byte type id as two qwords through the pointer in arg1. The call site in
  // FUN_1416797d0 confirms arg0 is the entity: `mov rcx, rdi` where `rdi = [rbp+0x160]`.
  //
  // THE BUG THIS FIXES: the first version did `args[1].readPointer().readByteArray(16)`, one
  // dereference too many, so it compared garbage and reported `transformLookups=0` on 553742 calls.
  // Rather than guess the byte order of the Transform GUID, this version RECORDS the 16 bytes of
  // every lookup that returns NULL, so the identity of the missing component is measured.
  function typeIdHex(arg) {
    try {
      const b = new Uint8Array(arg.readByteArray(16));
      let hex = '';
      for (let i = 0; i < 16; i++) hex += ('0' + b[i].toString(16)).slice(-2);
      return hex;
    } catch (e) { return null; }
  }

  Interceptor.attach(rva(%LOOKUP%), {
    onEnter(args) {
      calls++;
      this.entity = args[0];
      this.typeHex = typeIdHex(args[1]);
    },
    onLeave(ret) {
      const isNull = ret.isNull();
      if (isNull) {
        // Every null lookup is recorded by the type id that was asked for. This is what names the
        // missing component empirically instead of trusting a byte-order guess.
        const k = this.typeHex || 'unreadable';
        nullByType[k] = (nullByType[k] || 0) + 1;
      }
      if (this.typeHex !== transformHex || transformHex === null) return;
      transformLookups++;
      if (!isNull) return;
      transformNulls++;
      let state = -1;
      try { state = this.entity.add(0x60).readU8() & 0xff; } catch (e) {}
      const key = 'state' + state;
      missing[key] = (missing[key] || 0) + 1;

      // THE CAP IS NOT OPTIONAL: the 2026-10-03 A/B did this unfiltered, performed 12488
      // attaches, stalled the game thread and the client left InGame with a connection failure.
      if (mode === 'attach' && attached < cap && (state === 0 || state === 2)) {
        // NEVER SWALLOW THE REASON. The previous run reported `attached=0` after the retval change
        // because the whole block was inside one silent catch, so 'the fix failed' and 'the fix threw'
        // were indistinguishable. Each step reports its own failure now.
        let t = null;
        try {
          t = factory();
        } catch (e) {
          send({ ev: 'factory-threw', error: String(e) });
          return;
        }
        if (t === null || t.isNull()) {
          send({ ev: 'factory-null' });
          return;
        }
        try {
          addComp(this.entity, t);
        } catch (e) {
          send({ ev: 'addcomp-threw', error: String(e) });
          return;
        }
        // RETURN THE COMPONENT, not just install it.
        //
        // MEASURED 2026-10-19 and it is the difference between 'installed' and 'effective': a run
        // that only INSTALLED did `attached=26` and the session still logged all 26 warnings, because
        // the caller of the lookup tests `rax` for null and logs when it is null - installing the
        // component does not change what the caller received. Rewriting `retval` is what makes the
        // caller see it, and it is the only way the warning count can drop: the log line is emitted
        // AFTER this return.
        try {
          ret.replace(t);
          attached++;
        } catch (e) {
          send({ ev: 'retval-threw', error: String(e), retvalType: typeof ret });
        }
      }
    }
  });

  send({ ev: 'ready', base: base.toString(16), mode: mode, cap: cap });
  setInterval(() => {
    send({ ev: 'stats', calls: calls, transformLookups: transformLookups,
           transformNulls: transformNulls, attached: attached, missingByState: missing,
           nullByType: nullByType, transformHex: transformHex });
  }, 5000);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("measure", "attach"), default="measure")
    ap.add_argument("--cap", type=int, default=40)
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    source = (JS.replace("%MODE%", json.dumps(args.mode))
                .replace("%CAP%", str(args.cap))
                .replace("%TGUID%", json.dumps(TRANSFORM_GUID_LE))
                .replace("%LOOKUP%", hex(LOOKUP))
                .replace("%FACTORY%", hex(FACTORY))
                .replace("%ADD_COMPONENT%", hex(ADD_COMPONENT)))

    device = frida.get_local_device()

    def discover():
        return next((p.pid for p in device.enumerate_processes()
                     if p.name.lower() == "newworld.exe"), None)

    pid = discover()
    if pid is None and args.wait:
        deadline = time.time() + args.wait
        while pid is None and time.time() < deadline:
            time.sleep(1)
            pid = discover()
    if pid is None:
        print("[lookup] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    out = probe_capture(f"transform-lookup-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")
    last: dict = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[lookup] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        fh.write(json.dumps(p) + "\n")
        fh.flush()
        if p.get("ev") == "ready":
            print(f"[lookup] {p['mode']} cap={p['cap']} base={p['base']}", flush=True)
        elif p.get("ev", "").endswith("-threw") or p.get("ev") == "factory-null":
            print(f"[lookup] !! {p['ev']} {p.get('error', '')[:200]}", flush=True)
        elif p.get("ev") == "stats":
            last.update(p)
            print(f"[lookup] calls={p['calls']} transformLookups={p['transformLookups']} "
                  f"transformNulls={p['transformNulls']} attached={p['attached']} "
                  f"missing={json.dumps(p['missingByState'])}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[lookup] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    fh.close()
    print()
    print(f"  FINAL calls={last.get('calls')} transformLookups={last.get('transformLookups')} "
          f"transformNulls={last.get('transformNulls')} attached={last.get('attached')}")
    print(f"  missing by entity state: {json.dumps(last.get('missingByState', {}))}")
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
