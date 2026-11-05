#!/usr/bin/env python3
"""Name the decoder/router that calls the client's record parser.

`FUN_146b701b0` is the parse step (validated: it runs in the Python control and starves
against the Rust server). It is reached through a vtable, so a static `--callers-of`
finds nothing. This probe records the return address of every parse call, which IS the
caller -- the decode/router -- and counts it. Run against the Python control to name the
router with 1.460-native evidence, then against the Rust server to see whether it fires.

Read-only. Usage:  python ef.py probe frida-carrier-parse-caller --timeout 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

PARSE = 0x146B701B0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) { send({ ev: 'error', error: 'no exe' }); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let parse = 0;
  const callers = {};
  Interceptor.attach(rva(0x146B701B0), {
    onEnter() {
      parse++;
      try {
        const r = this.returnAddress.sub(base).toString(16);
        callers[r] = (callers[r] || 0) + 1;
        if (callers[r] <= 2) send({ ev: 'caller', caller_rva: r, n: parse });
      } catch (e) {}
    }
  });
  rpc.exports = { status() { return { parse: parse, callers: callers }; } };
  send({ ev: 'ready', base: base.toString(16) });
}
"""


def find_game_pid():
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
        print("[pc] no NewWorld.exe")
        return 1
    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-parse-caller-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + chr(10)); fh.flush()
            print(f"[pc] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[pc] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[pc] live -> {out}", flush=True)
    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(f"[pc] parse={st['parse']} callers={json.dumps(st['callers'])}", flush=True)
            except Exception as exc:
                print("[pc] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
