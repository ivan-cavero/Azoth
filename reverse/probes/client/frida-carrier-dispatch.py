#!/usr/bin/env python3
"""Which handlers does the client's record dispatcher invoke? (Rust vs Python)

CONTEXT. Rung 15 is stuck against our Rust server because the client never dispatches our
ladder records to their handlers (`frida-carrier-65c-handler.py`: 0x65c handler 0 against
Rust, 1 against the Python world). `FUN_14647c210` is the generic dispatcher: it resolves a
handler from a table and calls it indirectly --

    v0  = *param_1
    A   = *(longlong *)(v0 + 0x68)
    off = *(int *)(A + 0x14)
    h   = **(void ***)(v0 + 0x68 + off)      // the code pointer it calls

This probe hooks `0x14647c210`, decodes `off` and the resolved handler RVA per call, and
counts them. Known handler RVAs: `0x65c` -> `0x146455ec0`, `0x663` -> `0x146447ac0`.

If our Rust run's handler map lacks `0x146455ec0`/`0x146447ac0` (while the Python run has
them), the ladder records are dropped BEFORE dispatch -- the fault is upstream of the
message processor.

Usage:
  python ef.py probe frida-carrier-dispatch --timeout 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

DISPATCH = 0x14647C210

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const counts = {};
  let total = 0;
  const sent = {};

  Interceptor.attach(rva(0x14647C210), {
    onEnter() {
      total++;
      let off = null, handler = null, rec = null;
      try {
        const p1 = this.context.rcx;
        const p2 = this.context.rdx;
        const v0 = p1.readPointer();
        const A = v0.add(0x68).readPointer();
        off = A.add(0x14).readS32();
        const pv2 = v0.add(0x68 + off);
        handler = pv2.readPointer().readPointer(); // (**(code **)*puVar2): two derefs
        rec = p2.readPointer();
      } catch (e) {}
      const hr = handler ? handler.sub(base).toString(16) : 'null';
      counts[hr] = (counts[hr] || 0) + 1;
      if (counts[hr] <= 2 && handler) {
        send({ ev: 'dispatch', handler_rva: hr, off: off, record: rec && rec.toString(), n: total });
      }
    }
  });

  rpc.exports = { status() { return { total: total, counts: counts }; } };
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
        print("[disp] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-dispatch-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[disp] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[disp] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[disp] live -> {out}", flush=True)
    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(f"[disp] total={st['total']} counts={json.dumps(st['counts'])}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("[disp] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
