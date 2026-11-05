#!/usr/bin/env python3
"""How deep is the client's inbound message queue? (Rust vs Python)

The drainer `FUN_146b6e7c0` pops from a concurrent queue at `processor+0x50`, and its
64-bit item count lives at `queue+0x30` (decompiled: `plVar5 = (longlong *)(piVar12 + 0xc);
*plVar5 = *plVar5 + -1;`, where piVar12 is an `int *`). A depth that reaches 1 proves a
record was ENQUEUED (the parse accepted it); a depth that stays 0 while the drainer runs
proves nothing is ever enqueued -- the loss is in the parse, before the queue.

Read-only. Usage:
  python ef.py probe frida-carrier-queue-depth --timeout 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

DRAIN = 0x146B6E7C0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let drains = 0;
  const queues = {};   // queue ptr -> {maxDepth, positives}
  function note(q) {
    const key = q.toString();
    let rec = queues[key];
    if (rec === undefined) { rec = { maxDepth: 0, positives: 0 }; queues[key] = rec; }
    return rec;
  }
  Interceptor.attach(rva(0x146B6E7C0), {
    onEnter() {
      drains++;
      try {
        const q = this.context.rcx.add(0x50).readPointer();
        if (!q.isNull()) {
          const rec = note(q);
          const d = q.add(0x30).readS64().toNumber();
          if (d > rec.maxDepth) rec.maxDepth = d;
          if (d > 0) {
            rec.positives++;
            if (rec.positives <= 5) send({ ev: 'depth', q: q.toString(), depth: d, drains: drains });
          }
        }
      } catch (e) {}
    }
  });

  rpc.exports = { status() { return { drains: drains, queues: queues }; } };
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
        print("[qd] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-queue-depth-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + chr(10))
            fh.flush()
            print(f"[qd] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[qd] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[qd] live -> {out}", flush=True)
    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(f"[qd] drains={st['drains']} queues={json.dumps(st['queues'])}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("[qd] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
