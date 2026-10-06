#!/usr/bin/env python3
"""Dump the component dispatch list + every component create/resolve during the burst.

Answers (in one run):
  1. What function pointers live in the dispatch list at r14+0x28 that
     FUN_14137a4db walks (the table that holds FUN_141761dd0 and SHOULD
     hold FUN_141763b70 / the GameTransformComponent path)?
  2. Which component names get created (FUN_141416740 = FNV create-by-name)
     and which type GUIDs get resolved (FUN_14145b890), per the burst?
  3. Does FUN_141763b70 run, and if so what does its entity resolver return?

Attach EARLY (scripts/run-instrumented-attempt.py flow), then enter the world.
"""

from __future__ import annotations

import argparse
import json
import time

import frida

JS = r"""
const m = Process.findModuleByName('NewWorld.exe');
const base = m.base;
const off = (va) => base.add(va - 0x140000000);

// Counting-only hooks during the burst (string/byteArray marshaling per call
// overwhelmed the pipe at burst rate in the first version and produced a
// silent log). Names/GUIDs are dumped post-burst via the buffers below.
const names = [];
const guids = [];
let dispatchFns = null;

Interceptor.attach(off(0x141416740), {
  onEnter(args) {
    if (names.length < 400) {
      try { names.push(args[2].readCString(48)); } catch (e) { names.push('?'); }
    }
  },
});

Interceptor.attach(off(0x14145b890), {
  onEnter(args) {
    if (guids.length < 400) {
      try {
        const p = args[2];
        guids.push(
          p.readU32().toString(16) + '-' + p.add(4).readU32().toString(16) +
          '-' + p.add(8).readU32().toString(16) + '-' + p.add(12).readU32().toString(16)
        );
      } catch (e) { guids.push('?'); }
    }
  },
});

// The dispatcher: dump the function pointers of the list it walks (r14+0x28).
Interceptor.attach(off(0x14137a4db), {
  onEnter() {
    if (dispatchFns) return;
    try {
      const head = this.context.r14.add(0x28);
      let node = head.readPointer();
      const fns = [];
      for (let i = 0; i < 24 && !node.equals(head); i++) {
        const fn = node.add(0x10).readPointer();
        if (!fn.isNull()) fns.push(fn.sub(base).toString(16));
        node = node.readPointer();
      }
      dispatchFns = fns;
    } catch (e) { dispatchFns = ['err:' + e]; }
  },
});

Interceptor.attach(off(0x141570190), { onEnter(args) {
  try {
    const node = args[0].add(0x20).readPointer().readPointer();
    const fn = node.add(0x10).readPointer();
    send({ev:'delegateTarget', fn: fn.sub(base).toString(16)});
  } catch (e) {}
}});
Interceptor.attach(off(0x146928d80), { onEnter(args) {
  send({ev:'mgrSetContext', tid: Process.getCurrentThreadId(), ctx: args[1].isNull() ? 'null' : args[1].toString()});
}});
Interceptor.attach(off(0x146929df0), { onEnter(args) {
  send({ev:'gateWriter'});
}});
Interceptor.attach(off(0x141570190), { onEnter() {
  send({ev:'portrayDelegate'});
}});
Interceptor.attach(off(0x141763b70), { onEnter(args) { send({ev:'b70'}); } });
Interceptor.attach(off(0x141582430), { onEnter(args) {
  let f = null;
  try { f = args[0].add(8).readU8(); } catch (e) {}
  send({ev:'xform', flag: f});
}});
Interceptor.attach(off(0x141761dd0), { onEnter(args) {
  send({ev:'cluster', p1: args[0].isNull() ? 'null' : 'obj'});
}});
Interceptor.attach(off(0x141717fc0), { onEnter(args) {
  send({ev:'record1', rec: args[1].toInt32(), tid: Process.getCurrentThreadId()});
}});

setInterval(() => {
  send({ev: 'agg', names: names.splice(0), guids: guids.splice(0),
        dispatchFns: dispatchFns});
  dispatchFns = null;
}, 2000);

Interceptor.attach(off(0x14644a070), { onEnter() {
  if (!globalThis.__fsmTid) { globalThis.__fsmTid = true; send({ev:'mainThreadTid', tid: Process.getCurrentThreadId()}); }
}});
send({ev: 'ready'});
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    import ctypes
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("si", repo / "scripts" / "send-input.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    wins = mod.find_windows("New World")
    if not wins:
        print("no New World window")
        return 1
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(wins[0][0], ctypes.byref(pid))
    print(f"attaching to pid {pid.value}", flush=True)

    session = frida.attach(pid.value)
    script = session.create_script(JS)
    from _paths import probe_capture

    out_path = probe_capture(f"dispatch-dump-{int(time.time())}.jsonl")
    out = out_path.open("a", encoding="utf-8")

    def on_message(msg, data):
        if msg.get("type") == "send":
            payload = msg["payload"]
            if data:
                payload = {**payload, "data": data.hex()}
            line = json.dumps(payload)
            print(line, flush=True)
            out.write(line + "\n")
            out.flush()
        elif msg.get("type") == "error":
            print("script error:", str(msg)[:200], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"probes live; log -> {out_path}", flush=True)
    deadline = time.time() + args.timeout
    try:
        while time.time() < deadline:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    import importlib.util
    raise SystemExit(main())
