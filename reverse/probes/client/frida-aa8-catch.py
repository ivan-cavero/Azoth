#!/usr/bin/env python3
"""Catch the WRITER of the connection object's +0xAA8 ("last response") field.

WHY. `FUN_14486c740` computes `now - *(obj+0xAA8)` every frame and
`FUN_14487b300` renders it as "Time since last response". Two live probes measured
that field as **stale** during the sampled windows. A later probe found eight
objects with `+0xAA8`; a single-object poke left the HUD red. A full-object memory
reset must be verified against the actual HUD and is not a server-side fix. The
protocol question remains which supported message opens the ALC conversation and
refreshes the appropriate stamp.

Static search of the 423,579-function corpus found **no** store of a clock value
into `[reg+0xAA8]`, so the writer is either reached indirectly or does not run at
all in our sessions. This probe answers it empirically:

  1. hook the per-frame reader `FUN_14486c740` and keep the object pointer;
  2. arm Frida's `MemoryAccessMonitor` on `[obj+0xAA0, 16)` and **re-arm after
     every access**, logging operation + the instruction pointer that faulted;
  3. dump the object's vtable (first 0x80 entries as RVAs) so the class can be
     identified offline by matching the entries against the corpus.

A `write` access at an instruction address is the answer: decompile that VA and
the message/event that reaches it names the missing server traffic. If only
`read` accesses ever appear, the writer genuinely never runs, and the next step is
to find which inbound message *should* reach it (the vtable dump is for that).

Read-only except for the access monitor's page protection; the process is the
private no-EAC client and Steam is never touched.

Usage:
  python az.py probe frida-aa8-catch --timeout 600
  python az.py probe frida-aa8-catch --watch 0xAA0 32 --timeout 600
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
  const off = (v) => '0x' + v.toString(16);
  const nowFn = new NativeFunction(rva(%NOW%), 'uint64', []);
  let obj = null;
  let armed = false;
  let reads = 0;
  let writes = 0;
  const ops = {};

  function arm() {
    if (obj === null || armed) return;
    armed = true;
    try {
      MemoryAccessMonitor.enable(
        [{ base: obj.add(%WATCH_OFF%), size: %WATCH_LEN% }],
        {
          onAccess(details) {
            armed = false;
            const from = details.from.sub(base).toString(16);
            const key = details.operation + '@' + from;
            ops[key] = (ops[key] || 0) + 1;
            if (details.operation === 'write') writes++;
            send({
              ev: 'access',
              op: details.operation,
              from_rva: from,
              addr: details.address.sub(base).toString(16),
              n: ops[key],
            });
            arm();
          }
        }
      );
    } catch (e) {
      send({ ev: 'arm-error', error: String(e) });
    }
  }

  Interceptor.attach(rva(%PERFRAME%), {
    onEnter(args) {
      if (obj === null && !args[0].isNull()) {
        obj = args[0];
        send({ ev: 'object', obj: obj.toString() });
        // Dump the vtable so the class can be identified offline.
        try {
          const vt = obj.readPointer();
          const entries = [];
          for (let i = 0; i < %VT_ENTRIES%; i++) {
            const p = vt.add(i * 8).readPointer();
            entries.push(p.sub(base).toString(16));
          }
          send({ ev: 'vtable', vt: vt.toString(), entries: entries });
        } catch (e) {
          send({ ev: 'vtable-error', error: String(e) });
        }
        arm();
      }
      reads++;
    }
  });

  Interceptor.attach(rva(%HUD%), {
    onEnter(args) {
      if (obj === null && !args[0].isNull()) { obj = args[0]; arm(); }
    }
  });

  rpc.exports = {
    status() {
      if (obj === null) return { waiting: true, reads: reads };
      const cur = nowFn();
      let v = null;
      try { v = obj.add(%WATCH_OFF%).readU64(); } catch (e) {}
      return {
        obj: obj.toString(),
        reads: reads,
        writes: writes,
        ops: ops,
        field: v === null ? null : v.toString(),
        now: cur.toString(),
        delta: v === null ? null : (cur - v),
      };
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
    ap.add_argument("--wait", type=int, default=300, help="seconds to wait for the process")
    ap.add_argument("--watch", type=lambda s: int(s, 0), default=0xAA0)
    ap.add_argument("--len", type=int, default=16)
    ap.add_argument("--vt-entries", type=int, default=0x60)
    ap.add_argument("--poll", type=float, default=10.0)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[aa8] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    js = (
        JS.replace("%WATCH_OFF%", hex(args.watch))
        .replace("%WATCH_LEN%", str(args.len))
        .replace("%VT_ENTRIES%", str(args.vt_entries))
        .replace("%NOW%", hex(NOW))
        .replace("%PERFRAME%", hex(PERFRAME))
        .replace("%HUD%", hex(HUD))
    )
    script = session.create_script(js)

    out = Path(__file__).resolve().parents[2] / "sessions" / f"aa8-catch-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")
    summary: dict[str, int] = {}

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            if payload.get("ev") == "access":
                key = f"{payload['op']}@{payload['from_rva']}"
                summary[key] = summary.get(key, 0) + 1
                if payload["op"] == "write" or summary[key] <= 3:
                    print(f"[aa8] {key} n={payload['n']}", flush=True)
            elif payload.get("ev") == "vtable":
                print(f"[aa8] vtable {payload['vt']} entries={len(payload['entries'])}", flush=True)
                print("  " + " ".join(payload["entries"][:24]), flush=True)
            else:
                print(f"[aa8] {payload}", flush=True)
        else:
            print("[aa8] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[aa8] live -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
            except Exception as exc:  # noqa: BLE001
                print("[aa8] status error:", exc, flush=True)
                continue
            if st.get("waiting"):
                print(f"[aa8] waiting for the object (reads={st.get('reads')})", flush=True)
                continue
            print(
                f"[aa8] delta={st['delta']} writes={st['writes']} "
                f"ops={json.dumps(st['ops'])}",
                flush=True,
            )
    except KeyboardInterrupt:
        pass
    print("[aa8] summary:", json.dumps(summary), flush=True)
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
