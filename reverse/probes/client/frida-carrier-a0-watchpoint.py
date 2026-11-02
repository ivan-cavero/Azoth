#!/usr/bin/env python3
"""Find the writer of the carrier state flag `[carrier+0xA0]` with a HARDWARE watchpoint.

WHY. The rung-15 gate (`WaitingForActorGameConnection` -> `WaitingForSpawnPoint`) is
client-local Carrier state: `[carrier+0xA0] == 2` (getter VA `0x145A934A0` =
`cmp dword [rcx+0xA0], 2 ; sete al ; ret`, 1.460.6033.6024067). A static sweep of the
image found no `mov dword [reg+0xA0], 2`, so the store that raises the flag to 2 can only
be found live. This probe hooks the getter to recover the carrier pointer, arms a
**write** hardware watchpoint on `[carrier+0xA0, 4)`, and reports the faulting store
address (its RVA) with the value written and a backtrace -- naming the code that should
have moved the client past rung 15.

Read-only: a hardware watchpoint does not modify memory. Private no-EAC client only.
Run against the PYTHON lab world, where the client does reach state 2.

STATUS 2026-11-02: WIP / UNVERIFIED. It attaches and arms the watchpoint only once the
getter runs; in the first live attempts the private client hung before character select,
so the getter never ran and no carrier store was caught. An early version also reported
unrelated exceptions; the handler now ignores PCs outside NewWorld.exe. It has NOT yet
been observed to capture the store of 2.

Usage:
  python ef.py probe frida-carrier-a0-watchpoint --timeout 600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

# 1.460.6033.6024067 / 30fe6461...: the `[carrier+0xA0] == 2` getter.
GETTER = 0x145A934A0
OFF = 0xA0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let carrier = null;
  let armed = false;
  let reads = 0;
  const hits = {};

  function report(kind, details) {
    try {
      const pc = details.context.pc;
      const pcRva = pc.sub(base).toString(16);
      let value = null;
      try { value = details.address.readU32(); } catch (e) {}
      const key = pcRva + ':' + value;
      hits[key] = (hits[key] || 0) + 1;
      if (hits[key] > 3) return;
      let bt = [];
      try {
        bt = Thread.backtrace(details.context, Backtracer.FUZZY)
               .map((a) => DebugSymbol.fromAddress(a).toString());
      } catch (e) {}
      send({ ev: kind, pc_rva: pcRva, value: value, n: hits[key],
             rax: details.context.rax.toString(16), backtrace: bt });
    } catch (e) {
      send({ ev: 'exc-error', error: String(e) });
    }
  }

  Process.setExceptionHandler(function (details) {
    // Only our watchpoint lives in NewWorld.exe; the client raises and handles its
    // own exceptions constantly, and a global handler that consumes those breaks it.
    try {
      const pc = details.context.pc;
      if (pc.compare(base) < 0 || pc.compare(base.add(mod.size)) >= 0) return false;
    } catch (e) { return false; }
    let value = null;
    try { value = details.address.readU32(); } catch (e) {}
    report(value === 2 ? 'hit2' : 'hit', details);
    return true; // resume: the store already happened
  });

  function arm(tid) {
    if (armed || carrier === null) return;
    armed = true;
    try {
      const t = Process.getThreadById(tid);
      const ok = t.setHardwareWatchpoint(0, carrier.add(%OFF%), 4, 'w');
      send({ ev: 'watchpoint', tid: tid, ok: ok, at: carrier.add(%OFF%).toString() });
    } catch (e) {
      send({ ev: 'watchpoint-error', error: String(e) });
    }
  }

  // The getter is a thiscall: RCX is the carrier. args[0] is that first argument.
  Interceptor.attach(rva(0x145A934A0), {
    onEnter(args) {
      if (carrier === null && !args[0].isNull()) {
        carrier = args[0];
        let cur = null;
        try { cur = carrier.add(%OFF%).readU32(); } catch (e) {}
        send({ ev: 'carrier', carrier: carrier.toString(), current: cur });
        arm(this.threadId);
      }
      reads++;
    }
  });

  rpc.exports = {
    status() {
      if (carrier === null) return { waiting: true, reads: reads, hits: hits };
      let v = null;
      try { v = carrier.add(%OFF%).readU32(); } catch (e) {}
      return { carrier: carrier.toString(), reads: reads, flag: v, hits: hits };
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
        print("[a0wp] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS.replace("%OFF%", hex(OFF)))

    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-a0-wp-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[a0wp] {json.dumps(payload)[:400]}", flush=True)
        else:
            print("[a0wp] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[a0wp] live -> {out}", flush=True)

    end = time.time() + args.timeout
    last = None
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
            except Exception as exc:  # noqa: BLE001
                print("[a0wp] status error:", exc, flush=True)
                continue
            if st.get("waiting"):
                print(f"[a0wp] waiting (reads={st.get('reads')})", flush=True)
                continue
            cur = st.get("flag")
            changed = "CHANGED" if (last is not None and cur != last) else ""
            last = cur
            print(f"[a0wp] carrier={st['carrier']} flag={cur} {changed} hits={st.get('hits')}", flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
