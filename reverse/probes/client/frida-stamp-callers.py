#!/usr/bin/env python3
"""Who CONSUMES the connection's "last response" stamp? (backtrace, deduped)

WHY. The HUD's red cable icon is `now - *(conn+0xAA0 + 8)`, and that field is written
exactly once, at connection construction (measured process-wide: 0 writes against
9.3 M reads). So the interesting question is no longer "who writes it" but **who reads
it and what do they decide with it** — because whatever that consumer is, it is the
code that thinks the server has gone silent.

The read instruction is `mov rax,[rcx+8]` at `0x1406c6a00`, a leaf getter that the
corpus cannot attribute (no direct callers anywhere: the calls are virtual). A live
backtrace is therefore the only way to name the consumer.

The probe hooks that getter, takes an accurate backtrace, and prints each **distinct
call chain once** with a hit count, so the output stays small while still covering
every consumer in the session. The frames are RVAs, to be resolved offline with
`python scripts/corpus-contains.py <rva>`.

Read-only. Private no-EAC client.

Usage:
  python ef.py probe frida-stamp-callers --timeout 300
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

GETTER = 0x1406C6A00     # mov rax,[rcx+8]; ret  -- reads the stamp at conn+0xAA0+8
PERFRAME = 0x14486C740   # per-frame reader that owns the connection object

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const chains = {};
  let total = 0;

  Interceptor.attach(rva(0x1406c6a00), {
    onEnter(args) {
      total++;
      if (total > 20000) return;      // keep the probe cheap; 20k hits is plenty
      let bt;
      try {
        bt = Thread.backtrace(this.context, Backtracer.ACCURATE)
               .map(a => a.sub(base).toString(16));
      } catch (e) { bt = ['bt-fail']; }
      const key = bt.slice(1, 5).join('>');   // skip our own hook frame
      chains[key] = (chains[key] || 0) + 1;
      if (chains[key] === 1) {
        send({ ev: 'chain', key: key, bt: bt.slice(0, 10), arg: args[0].sub(base).toString(16) });
      }
    }
  });

  rpc.exports = {
    status() { return { total: total, distinct: Object.keys(chains).length }; }
  };

  send({ ev: 'ready', base: base.toString(16) });
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--poll", type=float, default=20.0)
    args = ap.parse_args()

    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    out = Path(__file__).resolve().parents[2] / "sessions" / f"stamp-callers-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[stamp] {json.dumps(payload)[:400]}", flush=True)
        else:
            print("[stamp] err:", str(m.get("description"))[:200], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[stamp] live -> {out}", flush=True)

    end = time.time() + args.timeout
    while time.time() < end:
        time.sleep(args.poll)
        try:
            st = script.exports_sync.status()
        except Exception as exc:  # noqa: BLE001
            print("[stamp] status error:", exc, flush=True)
            continue
        print(f"[stamp] hits={st['total']} distinct_chains={st['distinct']}", flush=True)
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
