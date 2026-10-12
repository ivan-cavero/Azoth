#!/usr/bin/env python3
"""Live ALC-door instrument: the ALC pointer, the stamp, and the types that arrive.

WHY, AND WHAT IT MUST SETTLE (item 1 + item 2 of the 2026-10-11 order)
=====================================================================
The HUD "Time since last response" stamp is `obj+0xAA8`, compared every frame
against `javelin.alc-server-timeout-for-input` (2000 ms) / `-for-ui-high`
(15000 ms). Two different client classes keep a field at that offset:

  * **class B** — the HUD object, primary vtable 0x1483874d8, read by
    `FUN_14486c740` (`sub r14,[rsi+0xAA8]`). This is the one the HUD paints.
  * **class A** — the connection / input-response state object reached as
    `*(owner+0x80)`, vtable 0x148399480, whose `+0xAA8` is read as a gate by
    `FUN_144837360` and written once by `FUN_1449309b0` (its vtable slot 11).

A previous probe read only class B and reported `aa0 = 0` and a frozen stamp.
This probe reads **both**, samples every few seconds, and — crucially — counts
the message types the client's typed dispatcher actually resolves
(`FUN_1461acfe0`), so the stamp can be correlated with the receipt of the
server's `0x1096`/`0x1097` input responses instead of being read in isolation.

Interpretation:
  * `alc_ptr` (the +0xAA0 pointer) stays null on both classes and the stamp never
    moves while `0x1096`/`0x1097` are being resolved -> the ALC conversation was
    never opened: the door is upstream of the ALC module, not inside it.
  * `alc_ptr` opens but the stamp stays frozen -> the door is inside the ALC
    module, and the server-side cvars `javelin-server.enable-alc-movement-reporting`,
    `alc-movement-reporting-period-seconds`, `ALC-max-input-to-combine` name it.
  * the resolver never reports `0x1096`/`0x1097` -> the input response is not
    reaching the typed path at all (a framing/channel problem, not ALC).

Read-only. Private no-EAC client.

Usage:
  python az.py probe frida-alc-door-live --timeout 1800 --poll 5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

PERFRAME = 0x14486C740      # class B per-frame read of +0xAA8 (the HUD painter)
CONSTRUCTOR = 0x1449309B0   # class A vtable slot 11: the only writer of class A +0xAA8
GATE = 0x144837360          # reads (*(this+0x80))+0xAA8 -> class A
RESOLVER = 0x1461ACFE0      # typed dispatcher: writes the 16-byte type GUID
DISPATCH = 0x146B6F190      # typed inbound dispatcher (control counter)
POS_READER = 0x143F97D10    # ReceivePlayerPositionClientMsg reader (control)
NOW = 0x141413890

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const nowFn = new NativeFunction(rva(0x141413890), 'uint64', []);
  let classB = null;
  let classA = null;
  let resolverCalls = 0;
  let dispatchCalls = 0;
  let posReaderCalls = 0;
  let ctorCalls = 0;
  const typeCounts = {};

  function readObj(obj) {
    if (obj === null || obj.isNull()) return null;
    try {
      return {
        obj: obj.toString(),
        aa0: obj.add(0xaa0).readPointer().toString(),
        aa8: obj.add(0xaa8).readU64().toString(),
        age_ms: nowFn().sub(obj.add(0xaa8).readU64()).toNumber(),
      };
    } catch (e) { return { obj: obj.toString(), err: String(e) }; }
  }

  Interceptor.attach(rva(0x14486c740), {
    onEnter(args) {
      if (classB === null && !args[0].isNull()) {
        classB = args[0];
        send({ ev: 'classB', ...readObj(classB) });
      }
    }
  });

  Interceptor.attach(rva(0x144837360), {
    onEnter(args) {
      if (classA !== null || args[0].isNull()) return;
      try {
        const p = args[0].add(0x80).readPointer();
        if (!p.isNull()) {
          classA = p;
          send({ ev: 'classA', via: 'gate', ...readObj(classA) });
        }
      } catch (e) {}
    }
  });

  Interceptor.attach(rva(0x1449309b0), {
    onEnter(args) {
      ctorCalls++;
      if (classA === null && !args[0].isNull()) {
        classA = args[0];
        send({ ev: 'classA', via: 'ctor', ...readObj(classA) });
      }
    }
  });

  Interceptor.attach(rva(0x1461acfe0), {
    onEnter(args) { this.out = args[1]; },
    onLeave(retval) {
      resolverCalls++;
      let hex = null;
      try {
        const b = new Uint8Array(this.out.readByteArray(16));
        hex = Array.from(b).map(x => x.toString(16).padStart(2, '0')).join('');
      } catch (e) { hex = 'read-fail'; }
      typeCounts[hex] = (typeCounts[hex] || 0) + 1;
      if (typeCounts[hex] === 1) send({ ev: 'new-type', hex: hex, n: resolverCalls });
    }
  });

  Interceptor.attach(rva(0x146b6f190), { onEnter() { dispatchCalls++; } });
  Interceptor.attach(rva(0x143f97d10), { onEnter() { posReaderCalls++; } });

  rpc.exports = {
    status() {
      return {
        classA: readObj(classA),
        classB: readObj(classB),
        resolver: resolverCalls,
        dispatch: dispatchCalls,
        pos_reader: posReaderCalls,
        ctor: ctorCalls,
        types: typeCounts,
      };
    }
  };

  send({ ev: 'ready', base: base.toString(16) });
}
"""

def find_game_pid() -> int | None:
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == "newworld.exe":
            return proc.pid
    return None

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--poll", type=float, default=5.0)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[alcdoor] no NewWorld.exe")
        return 1

    index: dict[str, int] = {}
    # parents[2] is reverse/ (where sessions/ lives); the client install is at the
    # repo root, so typeindex.json needs parents[3].
    ti = Path(__file__).resolve().parents[3] / "private-client" / "runtime" / "typeindex.json"
    if ti.is_file():
        data = json.loads(ti.read_text(encoding="utf-8"))
        for i, g in enumerate(data.get("typeIndex", [])):
            if g:
                index[g.lower()] = i

    def name_of(hex16: str) -> str:
        g = hex16.lower()
        swapped = (g[6:8] + g[4:6] + g[2:4] + g[0:2] + g[10:12] + g[8:10]
                   + g[14:16] + g[12:14] + g[16:])
        for cand in (g, swapped):
            if cand in index:
                return f"index {index[cand]}"
        return "?"

    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[2] / "sessions" / f"alc-door-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            if payload.get("ev") == "new-type":
                payload["name"] = name_of(payload["hex"])
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[alcdoor] {json.dumps(payload)[:260]}", flush=True)
        else:
            print("[alcdoor] err:", str(m.get("description"))[:200], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[alcdoor] live -> {out}", flush=True)

    end = time.time() + args.timeout
    while time.time() < end:
        time.sleep(args.poll)
        try:
            st = script.exports_sync.status()
        except Exception as exc:  # noqa: BLE001
            print("[alcdoor] status error:", exc, flush=True)
            continue
        st["ev"] = "status"
        st["ts"] = time.time()
        fh.write(json.dumps(st) + "\n")
        fh.flush()
        ca = st.get("classA") or {}
        cb = st.get("classB") or {}
        named = {name_of(k): v for k, v in (st.get("types") or {}).items()}
        print(
            f"[alcdoor] A.aa0={ca.get('aa0')} A.aa8={ca.get('aa8')} A.age={ca.get('age_ms')} "
            f"B.aa0={cb.get('aa0')} B.aa8={cb.get('aa8')} B.age={cb.get('age_ms')} "
            f"ctor={st['ctor']} dispatch={st['dispatch']} pos={st['pos_reader']} "
            f"types={named}",
            flush=True,
        )
    session.detach()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
