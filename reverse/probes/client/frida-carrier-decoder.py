#!/usr/bin/env python3
"""Which wire types does the client DECODE from the inbound stream? (Rust vs Python)

STATUS: the VAs below are INADVERTENTLY inherited from the 1.400 records and DO NOT fire in
1.460 -- measured 2026-11-05: against the PYTHON control (which reaches InGame) this probe
reports `decodes=0 dispatch=0 pushes=0`, exactly like the Rust run, so it measures nothing.
Superseded by `frida-carrier-queue-depth.py`, which is validated (Python maxDepth>0, Rust 0).
Keep only as a template; every address MUST be validated against the Python control before
it is used to conclude a negative.

CONTEXT. Against the Rust server the `0x65c` record is never dispatched, while against the
Python lab it is. The framing is byte-parity, so the question is WHERE the record dies:
in the record decoder (length vlq / unmarshal) or in the queue/dispatch.

Instrument: hook the record-decoder candidate `FUN_146b6ea20` (1.460; the 1.400 landmark
`javelin_inbound_decode_entry` sits at the same offset after the drainer `FUN_146b6e7c0`),
log the bytes its buffer holds, and report every `00 01 <type>` typed preamble it carries.
Also count drainer calls as a liveness control.

A type seen here but never dispatched  -> the queue/dispatch is the loss.
A type never seen here               -> the decoder drops it (length/unmarshal).

Usage:
  python ef.py probe frida-carrier-decoder --timeout 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

DECODER = 0x146B6EB70    # inbound decode entry (V6 slot +0x10)
TYPE_DISPATCH = 0x146B6F190  # ten-GUID switch; everything else is queued
DRAIN = 0x146B6E7C0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const types = {};
  const sentTypes = {};
  let decodes = 0, drains = 0, dispatch = 0, pushes = 0;
  const guids = {};

  function note(t) {
    types[t] = (types[t] || 0) + 1;
    if (sentTypes[t] === undefined) { sentTypes[t] = 0; }
    if (types[t] <= 2) send({ ev: 'decode', type: t, n: types[t] });
  }

  // Look for the typed preamble `00 01 <u16 type>` anywhere in the first 64 bytes.
  function scan(p) {
    try {
      const b = new Uint8Array(p.readByteArray(64));
      for (let i = 0; i + 3 < b.length; i++) {
        if (b[i] === 0x00 && b[i + 1] === 0x01) {
          const t = '0x' + ((b[i + 2] << 8) | b[i + 3]).toString(16);
          note(t);
          return;
        }
      }
    } catch (e) {}
  }

  Interceptor.attach(rva(0x146B6EB70), {
    onEnter() {
      decodes++;
      // The buffer pointer is one of the first two arguments; try both.
      try { scan(this.context.rcx); } catch (e) {}
      try { scan(this.context.rdx); } catch (e) {}
    }
  });

  Interceptor.attach(rva(0x146B6E7C0), {
    onEnter() {
      drains++;
      // Drainer: rcx=processor. Read the first popped node's object vtable[+0x30]
      // (the 16-byte type GUID the dispatch compares). Guarded: any read failure
      // is silent, and nothing here writes memory.
      try {
        const q = this.context.rcx.add(0x50).readPointer();
        const head = q.add(0x28).readU32();
        const cap = q.add(0x20).readU32();
        const base2 = q.add(0x18).readPointer();
        if (!base2.isNull() && cap > 0) {
          const node = base2.add((head & (cap - 1)) * 8).readPointer();
          if (!node.isNull()) {
            const obj = node.readPointer();
            if (!obj.isNull()) {
              const vt = obj.readPointer().readPointer(); // object vtable
              const g = vt.add(0x30).readByteArray(16);
              const hex = Array.from(new Uint8Array(g)).map(x => x.toString(16).padStart(2,'0')).join('');
              guids[hex] = (guids[hex] || 0) + 1;
              if (guids[hex] <= 2) send({ ev: 'guid', guid: hex, n: guids[hex] });
            }
          }
        }
      } catch (e) {}
    }
  });
  Interceptor.attach(rva(0x146B6F190), { onEnter() { dispatch++; } });

  rpc.exports = { status() { return { decodes: decodes, drains: drains, dispatch: dispatch, pushes: pushes, types: types, guids: guids }; } };
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
        print("[dec] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-decoder-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[dec] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[dec] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[dec] live -> {out}", flush=True)
    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(f"[dec] decodes={st['decodes']} dispatch={st['dispatch']} pushes={st['pushes']} drains={st['drains']} types={json.dumps(st['types'])} guids={json.dumps(st['guids'])}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("[dec] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
