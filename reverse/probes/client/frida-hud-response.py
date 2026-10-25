#!/usr/bin/env python3
"""Watch (and optionally reset) the client's "last response" timestamp.

WHY. The HUD connection indicator is driven by a timestamp the client keeps at
`obj + 0xAA8`. Two functions read it and both compute `now - *(obj+0xAA8)`:

  * `FUN_14486c740` — per-frame update, `uVar25 = lVar12 - *(longlong *)(param_1 + 0xaa8)`
  * `FUN_14487b300` — HUD render, formats "Time since last response: %s"

Static analysis found **no direct store** to that field anywhere in `.text`, and a
live session sampled it as **frozen**. If nothing ever writes it, the difference
grows without bound and the HUD can only ever show a bad connection -- which is
exactly the red cable the user sees while the wire is demonstrably healthy.

This probe settles it in two steps:

  1. `--mode read` (default): hook the per-frame reader, read `obj+0xAA8` and the
     client's own clock (`FUN_141413890`), and log the difference. Frozen field =>
     the HUD cannot recover no matter what the server sends.
  2. `--mode poke`: WRITE the current clock into the first object captured by this
     probe and report the memory values. The probe does not capture the HUD image
     and does not reset all objects. A single-object poke did not clear the icon;
     correlate any future multi-object test with screenshots, and do not treat a
     memory poke as a wire-level ALC fix.

The poke writes an 8-byte tick counter that the client itself writes, so it is
reversible and low risk; the process is a private no-EAC client and Steam is never
touched.

Usage:
  python ef.py probe frida-hud-response --wait 300 --timeout 900
  python ef.py probe frida-hud-response --mode poke --timeout 1200
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import frida

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import probe_capture  # noqa: E402

IMAGE_BASE = 0x140000000
PERFRAME = 0x14486C740   # FUN_14486c740(param_1) reads *(param_1 + 0xAA8)
HUD = 0x14487B300        # FUN_14487b300 reads the same field for the HUD text
NOW = 0x141413890        # FUN_141413890() -> the client's monotonic tick source
FIELD = 0xAA8

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const nowFn = new NativeFunction(rva(%NOW%), 'uint64', []);
  let obj = null;
  let reads = 0;
  let hudCalls = 0;
  let lastValue = null;
  const poke = %POKE%;

  function readField() {
    if (obj === null) return null;
    try { return obj.add(%FIELD%).readU64(); } catch (e) { return null; }
  }

  Interceptor.attach(rva(%PERFRAME%), {
    onEnter(args) {
      if (obj === null) obj = args[0];
      reads++;
    }
  });

  Interceptor.attach(rva(%HUD%), {
    onEnter(args) {
      if (obj === null) obj = args[0];
      hudCalls++;
    }
  });

  rpc.exports = {
    status() {
      if (obj === null) return { waiting: true, reads: reads, hudCalls: hudCalls };
      const cur = nowFn();
      const v = readField();
      return {
        obj: obj.toString(),
        reads: reads,
        hudCalls: hudCalls,
        field: v === null ? null : v.toString(),
        now: cur.toString(),
        // the client computes now - field; report both as numbers when sane
        delta_ticks: (v === null) ? null : (cur - v),
      };
    },
    poke() {
      if (obj === null) return { error: 'no object yet' };
      const before = readField();
      const cur = nowFn();
      try {
        obj.add(%FIELD%).writeU64(cur);
      } catch (e) {
        return { error: String(e) };
      }
      const after = readField();
      send({ ev: 'poked', before: before === null ? null : before.toString(),
             wrote: cur.toString(), after: after === null ? null : after.toString() });
      return { ok: true, before: before === null ? null : before.toString(),
               after: after === null ? null : after.toString() };
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


def wait_for_game(wait: float) -> int | None:
    deadline = time.time() + wait
    while time.time() < deadline:
        pid = find_game_pid()
        if pid is not None:
            return pid
        time.sleep(2)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--wait", type=float, default=300.0)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--mode", choices=("read", "poke"), default="read",
                    help="read = observe only; poke = also write the clock once")
    ap.add_argument("--poke-every", action="store_true",
                    help="with --mode poke, keep resetting the field on every sample "
                         "so the HUD difference stays small while the icon is checked")
    args = ap.parse_args()

    pid = wait_for_game(args.wait)
    if pid is None:
        print(f"NewWorld.exe not running after {args.wait:.0f}s", flush=True)
        return 1
    print(f"attaching to NewWorld.exe pid {pid}", flush=True)

    out_path = probe_capture(f"hud-response-{int(time.time())}.jsonl")
    out = out_path.open("a", encoding="utf-8")

    session = frida.attach(pid)
    script = session.create_script(
        JS.replace("%PERFRAME%", hex(PERFRAME))
        .replace("%HUD%", hex(HUD))
        .replace("%NOW%", hex(NOW))
        .replace("%FIELD%", hex(FIELD))
        .replace("%POKE%", "true" if args.mode == "poke" else "false")
    )

    seen: list[dict] = []

    def on_message(message, _data):
        if message.get("type") == "send":
            payload = message["payload"]
            if payload.get("ev") == "ready":
                print(f"[hud] hooks live base={payload['base']}", flush=True)
            elif payload.get("ev") == "poked":
                print(f"[hud] POKED before={payload['before']} after={payload['after']}",
                      flush=True)
                out.write(json.dumps(payload) + "\n")
                out.flush()
        elif message.get("type") == "error":
            print("script error:", message.get("description", "")[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[hud] logging to {out_path}", flush=True)

    deadline = time.time() + args.timeout
    next_at = time.time() + 15
    poked = False
    try:
        while time.time() < deadline:
            if time.time() >= next_at:
                next_at = time.time() + args.interval
                st = script.exports_sync.status()
                if st.get("waiting"):
                    print(f"[hud] waiting (per-frame reads={st['reads']})", flush=True)
                    continue
                row = {"t": time.strftime("%H:%M:%S", time.gmtime()), **st}
                out.write(json.dumps(row) + "\n")
                out.flush()
                delta = st.get("delta_ticks")
                frozen = ""
                if seen and st.get("field") == seen[-1].get("field"):
                    frozen = "  <== FIELD FROZEN"
                seen.append(st)
                print(f"[hud] {row['t']}Z field={st['field']} now={st['now']} "
                      f"delta={delta} reads={st['reads']} hud={st['hudCalls']}{frozen}",
                      flush=True)
                if args.mode == "poke" and (args.poke_every or not poked) and len(seen) >= 3:
                    poked = True
                    res = script.exports_sync.poke()
                    if args.poke_every:
                        d = res.get("after")
                        print(f"[hud] re-poked -> {d} (delta kept small)", flush=True)
                    else:
                        print(f"[hud] poke result: {res}", flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            st = script.exports_sync.status()
            print(f"\n[hud] final: {st}")
        except Exception as exc:  # noqa: BLE001
            print(f"[hud] final status failed: {exc}")
        session.detach()
        out.close()

    if len(seen) >= 2:
        values = {s.get("field") for s in seen}
        print(f"\n[hud] distinct field values across {len(seen)} samples: {len(values)}")
        if len(values) == 1:
            print("[hud] VERDICT: the timestamp is FROZEN -- nothing writes it, so the")
            print("       HUD difference grows forever and the indicator can only degrade.")
        else:
            print("[hud] VERDICT: the field DOES change; something writes it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
