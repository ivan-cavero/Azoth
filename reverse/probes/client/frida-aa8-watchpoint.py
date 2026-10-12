#!/usr/bin/env python3
"""Find the writer of the connection object's +0xAA8 with a HARDWARE watchpoint.

WHY. `FUN_14486c740` computes `now_ms - *(obj+0xAA8)` every frame and
`FUN_14487b300` renders it as "Time since last response"; the HUD's red cable icon
is a pure function of that number. A sampled object had a **frozen** timestamp. Later probes found eight objects
with `+0xAA8`; a poke of only the first object left the HUD red. This read-only
watchpoint does not establish that resetting every object clears the live indicator,
and no memory poke proves a server-side ALC handshake.

A static sweep of the 423,579-function corpus found no store of a clock into
`[reg+0xAA8]`, which is exactly the kind of result that is usually an artifact of
how the store is rendered. A hardware watchpoint does not care how the store is
written:

  * hook the per-frame reader to get the object pointer;
  * `Thread.setHardwareWatchpoint` on `[obj+0xAA8, 8)` with condition `w`;
  * `Process.setExceptionHandler` reports the faulting instruction address (the
    store) and the value, then resumes so the client keeps running.

The faulting VA *is* the answer: decompile it and the caller chain names the
message/event that should refresh the stamp.

Read-only: hardware watchpoints do not modify memory. Private no-EAC client.

Usage:
  python az.py probe frida-aa8-watchpoint --timeout 900
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

PERFRAME = 0x14486C740
HUD = 0x14487B300
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
  let set = false;
  let reads = 0;
  const seen = {};

  Process.setExceptionHandler(function (details) {
    try {
      const pc = details.context.pc;
      const key = pc.sub(base).toString(16);
      seen[key] = (seen[key] || 0) + 1;
      if (seen[key] <= 5) {
        send({ ev: 'hit', pc_rva: key, n: seen[key],
               rax: details.context.rax.toString(16),
               addr: (details.address || ptr(0)).toString() });
      }
    } catch (e) {
      send({ ev: 'exc-error', error: String(e) });
    }
    return true;   // resume: the store already happened
  });

  function setup(tid) {
    if (set || obj === null) return;
    set = true;
    try {
      const t = Process.getThreadById(tid);
      const ok = t.setHardwareWatchpoint(0, obj.add(%OFF%), 8, 'w');
      send({ ev: 'watchpoint', tid: tid, ok: ok, at: obj.add(%OFF%).toString() });
    } catch (e) {
      send({ ev: 'watchpoint-error', error: String(e) });
    }
  }

  Interceptor.attach(rva(0x14486c740), {
    onEnter(args) {
      if (obj === null && !args[0].isNull()) {
        obj = args[0];
        send({ ev: 'object', obj: obj.toString(), field: obj.add(%OFF%).readU64().toString() });
        setup(this.threadId);
      }
      reads++;
    }
  });

  Interceptor.attach(rva(0x14487b300), {
    onEnter(args) {
      if (obj === null && !args[0].isNull()) { obj = args[0]; setup(this.threadId); }
    }
  });

  rpc.exports = {
    status() {
      if (obj === null) return { waiting: true, reads: reads };
      let v = null;
      try { v = obj.add(%OFF%).readU64(); } catch (e) {}
      return { obj: obj.toString(), reads: reads, field: v === null ? null : v.toString(),
               now: nowFn().toString(), hits: seen };
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
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--off", type=lambda s: int(s, 0), default=0xAA8)
    ap.add_argument("--poll", type=float, default=20.0)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[aa8wp] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    js = JS.replace("%OFF%", hex(args.off))
    script = session.create_script(js)

    out = Path(__file__).resolve().parents[2] / "sessions" / f"aa8-wp-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[aa8wp] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[aa8wp] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[aa8wp] live -> {out}", flush=True)

    end = time.time() + args.timeout
    last = None
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
            except Exception as exc:  # noqa: BLE001
                print("[aa8wp] status error:", exc, flush=True)
                continue
            if st.get("waiting"):
                print(f"[aa8wp] waiting (reads={st.get('reads')})", flush=True)
                continue
            cur = st.get("field")
            changed = "CHANGED" if (last is not None and cur != last) else ""
            last = cur
            print(f"[aa8wp] field={cur} now={st['now']} {changed}", flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
