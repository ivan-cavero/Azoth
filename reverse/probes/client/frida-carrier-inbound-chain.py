#!/usr/bin/env python3
"""Does the inbound parse chain run against the Rust server? (three validated-adjacent hooks)

Chain (1.460, all inside NewWorld.exe next to the drainer):
  FUN_146b701b0  parse: builds the typed object from the inbound record
  FUN_146b707d0  type dispatch: ten-GUID switch; fallback enqueues
  FUN_146b6d590  enqueue: pushes {object, owner} into the ring, bumps queue+0x30

`FUN_146b6d590` is validated (captured as the enqueue PC against the Python control).
Run against the Rust server: if the PARSE never fires, the bytes never reach the parser
(routing/DTLS layer); if the parse fires but the enqueue never does, the parse REJECTS our
records. Read-only.

Usage:  python ef.py probe frida-carrier-inbound-chain --timeout 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

PARSE = 0x146B701B0
DISPATCH = 0x146B707D0
ENQUEUE = 0x146B6D590

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) { send({ ev: 'error', error: 'no exe' }); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let parse = 0, dispatch = 0, enqueue = 0;
  Interceptor.attach(rva(0x146B701B0), { onEnter() { parse++; } });
  Interceptor.attach(rva(0x146B707D0), { onEnter() { dispatch++; } });
  Interceptor.attach(rva(0x146B6D590), { onEnter() { enqueue++; } });
  rpc.exports = { status() { return { parse: parse, dispatch: dispatch, enqueue: enqueue }; } };
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
        print("[chain] no NewWorld.exe")
        return 1
    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-chain-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + chr(10)); fh.flush()
            print(f"[chain] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[chain] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[chain] live -> {out}", flush=True)
    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(f"[chain] parse={st['parse']} dispatch={st['dispatch']} enqueue={st['enqueue']}", flush=True)
            except Exception as exc:
                print("[chain] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
