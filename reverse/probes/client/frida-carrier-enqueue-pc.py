#!/usr/bin/env python3
"""Name the client code that ENQUEUES an inbound record, using the Python control.

Method (1.460-native, no inherited VAs): hook the drainer `FUN_146b6e7c0` (validated), read
its queue (`processor+0x50`), and arm a WRITE hardware watchpoint on the queue's int64 item
count (`queue+0x30`). The drainer decrements that counter, so its own writes are filtered by
PC range; every OTHER writer is the ENQUEUE (the parse step that accepted a record). Run
against the PYTHON world first -- the queue really fills there (maxDepth 28), so the enqueue
must fire and its PC is named with evidence. Then run against the Rust server and compare.

Read-only: hardware watchpoints do not modify memory.

Usage:
  python ef.py probe frida-carrier-enqueue-pc --timeout 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

DRAIN = 0x146B6E7C0
DRAIN_END = 0x146B6EA13

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let queue = null, armed = false, drains = 0;
  const hits = {};

  Process.setExceptionHandler(function (details) {
    try {
      const pc = details.context.pc;
      if (pc.compare(base) < 0 || pc.compare(base.add(mod.size)) >= 0) return false;
      const r = parseInt(pc.sub(base).toString(16), 16);
      if (r >= 0x6B6E7C0 && r < 0x6B6EA13) return true;   // drainer RVA range (its own decrement)
      const key = r.toString(16);
      hits[key] = (hits[key] || 0) + 1;
      if (hits[key] <= 3) {
        let value = null;
        try { value = details.address.readS64().toNumber(); } catch (e) {}
        send({ ev: 'enqueue', pc_rva: key, depth: value, tid: details.threadId, n: hits[key] });
      }
      return true;
    } catch (e) { return false; }
  });

  function armAll() {
    if (armed || queue === null) return;
    armed = true;
    // The enqueue runs on the network/parse thread while the drainer runs on the frame
    // thread, and a hardware watchpoint is per-thread: arm it on every live thread.
    let n = 0;
    Process.enumerateThreads().forEach(function (t) {
      try {
        if (Process.getThreadById(t.id).setHardwareWatchpoint(0, queue.add(0x30), 8, 'w')) n++;
      } catch (e) {}
    });
    send({ ev: 'watchpoint', threads: n, at: queue.add(0x30).toString() });
  }

  Interceptor.attach(rva(0x146B6E7C0), {
    onEnter() {
      drains++;
      if (queue === null) {
        try {
          const q = this.context.rcx.add(0x50).readPointer();
          if (!q.isNull()) { queue = q; send({ ev: 'queue', q: q.toString() }); armAll(); }
        } catch (e) {}
      }
    }
  });

  rpc.exports = { status() { return { drains: drains, armed: armed, hits: hits }; } };
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
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--poll", type=float, default=15.0)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[enq] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-enqueue-pc-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + chr(10))
            fh.flush()
            print(f"[enq] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[enq] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[enq] live -> {out}", flush=True)
    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(f"[enq] drains={st['drains']} armed={st['armed']} hits={json.dumps(st['hits'])}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("[enq] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
