#!/usr/bin/env python3
"""Does the client ACCEPT the state bundles we send? Read the replication gate.

WHY THIS EXISTS
===============
`AZOTH_REPLAY_STATE_STREAM` sends captured type-0x08 bundles on a timer. The lever's own
comment in `services/world/src/azoth_world/rep.py` records the trap: without the seq rewrite
the bundles keep their captured counter, which is at or below the client's high-water, so the
replication gate **discards every one of them silently**. Measured 2026-10-12: a session sent
697 `state-stream` events with **0** client-side errors and the world behaved exactly as if
nothing had been sent. "No errors" is therefore not evidence that anything applied.

This probe turns that into a number. The gate is `FUN_14643e7b0`; the atlas records its
condition as

    msg.clientContextInstanceId == port[+0x80]   AND   *(u64*)(msg+0x28) > port[+0x78]

with `FUN_1406d97b0` = `return msg+0x28` (the sequence) and `FUN_1406c10a0` =
`return byte [msg+0x30]` (the instance id). So hooking the gate and reading those two fields on
entry, plus the return value on leave, says per call: which sequence arrived and whether the
gate let it through. That is what decides whether a state-stream A/B measured anything.

Also reports the client's high-water directly when it can be found, and counts how many
distinct sequences were ACCEPTED, so "the stream applied" becomes falsifiable.

Read-only: it hooks one function, reads two fields and the return value. No writes.

Usage:
  python ef.py probe frida-repl-gate --timeout 120
"""

from __future__ import annotations

import argparse
import collections
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

GATE = 0x14643E7B0  # the unreliable-replication acceptance gate
SEQ_GETTER = 0x1406D97B0  # return msg+0x28
INSTANCE_GETTER = 0x1406C10A0  # return byte [msg+0x30]

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let calls = 0, accepted = 0, rejected = 0;
  const seqSeen = new Map();      // seq -> {n, accepted}
  const instSeen = new Map();
  let lastError = null;

  Interceptor.attach(rva(0x14643e7b0), {
    onEnter(args) {
      calls++;
      this.msg = args[0];
      try {
        this.seq = this.msg.add(0x28).readU64();
        this.inst = this.msg.add(0x30).readU8();
      } catch (e) {
        this.seq = null; this.inst = null;
        if (!lastError) lastError = String(e);
      }
    },
    onLeave(ret) {
      const ok = !ret.isNull() && ret.toInt32() !== 0;
      if (ok) accepted++; else rejected++;
      if (this.seq !== null) {
        const s = this.seq.toString();
        const e = seqSeen.get(s) || { n: 0, accepted: 0 };
        e.n++; if (ok) e.accepted++;
        seqSeen.set(s, e);
      }
      if (this.inst !== null) {
        const k = String(this.inst);
        const e = instSeen.get(k) || { n: 0, accepted: 0 };
        e.n++; if (ok) e.accepted++;
        instSeen.set(k, e);
      }
    },
  });

  rpc.exports = {
    stats() {
      const top = Array.from(seqSeen.entries())
        .map(([seq, v]) => ({ seq: Number(seq), n: v.n, accepted: v.accepted }))
        .sort((a, b) => b.n - a.n).slice(0, 25);
      return {
        calls: calls, accepted: accepted, rejected: rejected,
        distinctSeqs: seqSeen.size,
        maxSeqSeen: seqSeen.size ? Math.max(...Array.from(seqSeen.keys()).map(Number)) : null,
        instances: Array.from(instSeen.entries()).map(([k, v]) => ({ inst: Number(k), ...v })),
        topSeqs: top,
        error: lastError,
      };
    },
    teardown() { try { Interceptor.detachAll(); return true; } catch (e) { return String(e); } },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--shutdown", choices=["kill", "detach"], default="detach")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[rg]", json.dumps(m), flush=True))
    script.load()
    print(f"[rg] attached to {args.process}", flush=True)

    capture = probe_capture(f"repl-gate-{int(time.time())}.jsonl")
    print(f"[rg] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                st = script.exports_sync.stats()
            except Exception as exc:  # noqa: BLE001
                print(f"[rg] stats error: {exc}", flush=True)
                time.sleep(2.0)
                continue
            fh.write(json.dumps({"t": time.time(), "stats": st}) + "\n")
            fh.flush()
            print(f"[rg] calls={st['calls']} accepted={st['accepted']} "
                  f"rejected={st['rejected']} distinctSeqs={st['distinctSeqs']} "
                  f"maxSeq={st['maxSeqSeen']}", flush=True)
            time.sleep(args.poll)

    strategy = safe_shutdown(session, script, kill=(args.shutdown == "kill"), device=device,
                             log=lambda m: print(f"[rg] {m}", flush=True))
    print(f"[rg] shutdown strategy: {strategy}", flush=True)
    print(f"[rg] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
