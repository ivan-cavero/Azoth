#!/usr/bin/env python3
"""Live ALC instrument: who, if anyone, moves the connection's "last response" stamp?

WHY, AND WHAT IT MUST SETTLE
============================
The HUD's red cable icon is a pure function of `now - *(conn+0xAA8)`, compared every
frame against two thresholds that were read out of the live process:

    red   = 15000 ms   (javelin.alc-server-timeout-for-ui-high)
    amber =  2000 ms   (javelin.alc-server-timeout-for-input / -for-ui)

Once the HUD stamp stops advancing, its age crosses the amber threshold at 2 s and the red threshold at 15 s; this is not a 20-minute session timer.
The stamp at `conn+0xAA8` is filled together with `conn+0xAA0`, `+0xA98` and `+0xAB0`
by the connection constructor `FUN_1449309b0`, from a four-qword struct returned by
`FUN_1416ba900(&stack, 0x70cd8b77)` — a singleton lookup keyed by a 32-bit tag.

An earlier probe armed a **thread** hardware watchpoint on `[conn+0xAA8, 8)` with the
`w` condition and saw zero writes. That result is not trustworthy on its own: a
hardware watchpoint only traps the thread it is set on, and the writer (if any) would
run on the network or game thread. This probe removes that hole:

  1. `MemoryAccessMonitor` is **process-wide** (page-level), so a write from any thread
     traps. It is armed on `[conn+0xAA8, 8)` and re-armed after every access, logging
     the operation and the faulting instruction.
  2. `FUN_1416ba900` is hooked with its tag argument, which answers the question that
     actually matters: **is the singleton that carries the stamp polled every frame?**
     If the tag `0x70cd8b77` is looked up periodically, the snapshot is live and only
     the copy into `conn` is missing; if it is looked up once, the stamp is a
     construction-time constant by design and the client is waiting for a *message*.
  3. Control counters, because a probe that reports zero everywhere is worthless
     until it is shown to count: `FUN_146b6f190` (the typed inbound dispatcher) and
     `FUN_143f97d10` (the `ReceivePlayerPositionClientMsg` reader). The dispatcher
     must be non-zero in a live session; if it is also zero, the hook addresses are
     wrong and every "0 calls" conclusion in the atlas has to be re-examined.

Read-only. Private no-EAC client.

Usage:
  python ef.py probe frida-alc-live --timeout 1500
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

PERFRAME = 0x14486C740      # per-frame: reads conn+0xAA8
CONSTRUCTOR = 0x1449309B0   # fills conn+0xA98..0xAB8 from the singleton
SINGLETON = 0x1416BA900     # FUN_1416ba900(container, tag) -> settings struct
STAMP_TAG = 0x70CD8B77      # the tag the constructor passes
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
  let obj = null;
  let armed = false;
  let accesses = 0;
  let writes = 0;
  const ops = {};
  const singletonTags = {};
  let singletonCalls = 0;
  let dispatchCalls = 0;
  let posReaderCalls = 0;
  let ctorCalls = 0;

  function arm() {
    if (obj === null || armed) return;
    armed = true;
    try {
      MemoryAccessMonitor.enable(
        [{ base: obj.add(0xaa8), size: 8 }],
        {
          onAccess(details) {
            armed = false;
            accesses++;
            const from = details.from.sub(base).toString(16);
            const key = details.operation + '@' + from;
            ops[key] = (ops[key] || 0) + 1;
            if (details.operation === 'write') writes++;
            if (accesses <= 20 || details.operation === 'write') {
              send({ ev: 'access', op: details.operation, from_rva: from, n: ops[key] });
            }
            arm();
          }
        }
      );
    } catch (e) {
      send({ ev: 'arm-error', error: String(e) });
    }
  }

  Interceptor.attach(rva(0x14486c740), {
    onEnter(args) {
      if (obj === null && !args[0].isNull()) {
        obj = args[0];
        send({ ev: 'object', obj: obj.toString(),
               aa0: obj.add(0xaa0).readPointer().toString(),
               aa8: obj.add(0xaa8).readU64().toString() });
        arm();
      }
    }
  });

  // Is the stamp's source singleton polled per frame, or read once at construction?
  Interceptor.attach(rva(0x1416ba900), {
    onEnter(args) {
      singletonCalls++;
      let tag = '?';
      try { tag = '0x' + args[1].toUInt32().toString(16); } catch (e) {}
      singletonTags[tag] = (singletonTags[tag] || 0) + 1;
      if (singletonTags[tag] === 1 && tag === '0x70cd8b77') {
        send({ ev: 'stamp-tag-looked-up', tag: tag, n: singletonCalls });
      }
    }
  });

  Interceptor.attach(rva(0x1449309b0), { onEnter() { ctorCalls++; } });
  Interceptor.attach(rva(0x146b6f190), { onEnter() { dispatchCalls++; } });
  Interceptor.attach(rva(0x143f97d10), { onEnter() { posReaderCalls++; } });

  rpc.exports = {
    status() {
      let out = {
        reads_of_stamp: accesses, writes_to_stamp: writes, ops: ops,
        dispatch: dispatchCalls, pos_reader: posReaderCalls, ctor: ctorCalls,
        singleton_calls: singletonCalls,
        stamp_tag_count: singletonTags['0x70cd8b77'] || 0,
      };
      if (obj !== null) {
        try {
          const stamp = obj.add(0xaa8).readU64();
          out.stamp = stamp.toString();
          out.age_ms = nowFn().sub(stamp).toNumber();
          out.alc_ptr = obj.add(0xaa0).readPointer().toString();
        } catch (e) { out.read_err = String(e); }
      }
      return out;
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
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--poll", type=float, default=30.0)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[alc] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[2] / "sessions" / f"alc-live-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[alc] {json.dumps(payload)[:260]}", flush=True)
        else:
            print("[alc] err:", str(m.get("description"))[:200], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[alc] live -> {out}", flush=True)

    end = time.time() + args.timeout
    while time.time() < end:
        time.sleep(args.poll)
        try:
            st = script.exports_sync.status()
        except Exception as exc:  # noqa: BLE001
            print("[alc] status error:", exc, flush=True)
            continue
        fh.write(json.dumps({"ev": "status", **st}) + "\n")
        fh.flush()
        print(
            f"[alc] age_ms={st.get('age_ms')} stamp_writes={st['writes_to_stamp']} "
            f"stamp_reads={st['reads_of_stamp']} tag70cd8b77={st['stamp_tag_count']} "
            f"dispatch={st['dispatch']} pos_reader={st['pos_reader']}",
            flush=True,
        )
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
