#!/usr/bin/env python3
"""Capture WHO decides to leave the world, with a backtrace.

WHY. Live private sessions END BY THEMSELVES at almost exactly 20 minutes after the
player spawns, cleanly: `CGame::ActorContainerDisconnect` -> `CGame exiting to main
menu` -> `Cleanup()`, with `transportError` 0 and `OnLocalNetworkConnectionWarning` 0.
Three consecutive measurements: 20:00, 20:01, 20:02.

Static work established the effect, not the cause:
  * `FUN_146444b10` logs "CGame exiting to main menu"; its exit is selected by the
    cvar `UIFeatures.g_exitToMainMenu` (string at 0x147fc8c70), and the sibling log
    text is "CGame exiting to desktop, instead of main menu" (0x147fc8ed8).
  * `FUN_146444b10` has **no direct callers** (callers.py: 0), so the decision is
    reached through a delegate/virtual dispatch -- exactly the shape that made the
    body gate hard to find too.

So the cause has to be read at runtime. This probe attaches to the known landmarks
and prints a **backtrace** for each, which converts an unreachable-by-xref decision
into an ordered call chain:

  * `FUN_146444b10`  -- the exit-to-main-menu routine itself
  * `FUN_146444e10`-family / `FUN_146445e10` -- the InGame REP activity watchdog;
    it is separate from the measured orderly return-to-menu at 20 minutes
  * `FUN_14486c740`  -- per-frame reader of `obj+0xAA8` ("last response")
  * `FUN_14487b300`  -- HUD render of the same field

and reports EVERY distinct object seen at `FUN_14486c740`, with its `+0xAA8` value and
age. An earlier version captured only the first object; if more than one connection
component exists, that alone would explain why resetting the field did not help.

Read-only except for the optional reset. Private runtime only; EAC is never involved.

Usage:
  python ef.py probe frida-exit-trace --wait 400 --timeout 1800
  python ef.py probe frida-exit-trace --reset-field   # also keep +0xAA8 fresh
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

EXIT_MAIN_MENU = 0x146444B10   # logs "CGame exiting to main menu"
WATCHDOG = 0x146445E10         # InGame activity watchdog
PERFRAME = 0x14486C740         # per-frame: reads obj+0xAA8
HUD = 0x14487B300              # HUD text from the same field
NOW = 0x141413890
FIELD = 0xAA8

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const modEnd = base.add(mod.size);
  const nowFn = new NativeFunction(rva(%NOW%), 'uint64', []);

  // short, readable backtrace: only frames inside the module.
  // ACCURATE fails here (returns nothing); FUZZY walks the frame chain and is
  // reliable enough to name the caller in the crash/hook context.
  function bt(ctx) {
    const frames = [];
    try {
      Thread.backtrace(ctx, Backtracer.FUZZY).slice(0, 14).forEach((a) => {
        if (a.compare(base) >= 0 && a.compare(modEnd) < 0) {
          frames.push('rva:0x' + a.sub(base).toString(16));
        }
      });
    } catch (e) { frames.push('bt-error:' + e); }
    if (frames.length === 0) frames.push('bt-empty');
    return frames;
  }

  const fieldObjs = new Map();   // obj -> { first, last, reads, min, max }
  let reset = %RESET%;

  function noteObj(p) {
    let e = fieldObjs.get(p.toString());
    if (!e) {
      if (fieldObjs.size >= 8) return null;
      e = { obj: p.toString(), first: null, last: null, reads: 0, min: null, max: null };
      fieldObjs.set(p.toString(), e);
      send({ ev: 'new-object', obj: p.toString(), backtrace: bt(this.context) });
    }
    return e;
  }

  Interceptor.attach(rva(%PERFRAME%), {
    onEnter(args) {
      const e = noteObj.call(this, args[0]);
      if (!e) return;
      e.reads++;
      try {
        const v = args[0].add(%FIELD%).readU64();
        e.first = e.first === null ? v.toString() : e.first;
        e.last = v.toString();
        e.min = e.min === null ? v : (v < e.min ? v : e.min);
        e.max = e.max === null ? v : (v > e.max ? v : e.max);
        if (reset) {
          // keep "time since last response" small on EVERY tracked object, not just
          // the first: an earlier run poked only object #1 and the 20-minute exit
          // still happened, so the test must cover all of them.
          for (const [, e] of fieldObjs.entries()) {
            try { ptr(e.obj).add(%FIELD%).writeU64(nowFn()); } catch (x) {}
          }
        }
      } catch (x) {}
    }
  });

  Interceptor.attach(rva(%HUD%), {
    onEnter(args) { noteObj.call(this, args[0]); }
  });

  Interceptor.attach(rva(%EXIT_MAIN_MENU%), {
    onEnter(args) {
      send({ ev: 'EXIT-MAIN-MENU', arg1: args[1].toInt32(), backtrace: bt(this.context) });
    }
  });

  Interceptor.attach(rva(%WATCHDOG%), {
    onEnter(args) {
      watchdogCalls++;
      if (watchdogCalls < 4) {
        send({ ev: 'watchdog', n: watchdogCalls, backtrace: bt(this.context) });
      }
    }
  });
  let watchdogCalls = 0;

  rpc.exports = {
    stats() {
      const out = [];
      for (const [k, e] of fieldObjs.entries()) {
        out.push({ obj: k, reads: e.reads, first: e.first, last: e.last,
                   min: e.min === null ? null : e.min.toString(),
                   max: e.max === null ? null : e.max.toString() });
      }
      send({ ev: 'stats', objects: out, watchdogCalls: watchdogCalls, reset: reset });
    },
    setReset(on) { reset = !!on; return reset; }
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
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--wait", type=float, default=400.0)
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--reset-field", action="store_true")
    args = ap.parse_args()

    pid = wait_for_game(args.wait)
    if pid is None:
        print(f"NewWorld.exe not running after {args.wait:.0f}s", flush=True)
        return 1
    print(f"attaching to NewWorld.exe pid {pid}", flush=True)

    out_path = probe_capture(f"exit-trace-{int(time.time())}.jsonl")
    out = out_path.open("a", encoding="utf-8")

    session = frida.attach(pid)
    script = session.create_script(
        JS.replace("%EXIT_MAIN_MENU%", hex(EXIT_MAIN_MENU))
        .replace("%WATCHDOG%", hex(WATCHDOG))
        .replace("%PERFRAME%", hex(PERFRAME))
        .replace("%HUD%", hex(HUD))
        .replace("%NOW%", hex(NOW))
        .replace("%FIELD%", hex(FIELD))
        .replace("%RESET%", "true" if args.reset_field else "false")
    )

    def on_message(message, _data):
        if message.get("type") == "send":
            payload = message["payload"]
            ev = payload.get("ev")
            out.write(json.dumps(payload) + "\n")
            out.flush()
            if ev == "ready":
                print(f"[exit] hooks live base={payload['base']}", flush=True)
            elif ev == "new-object":
                print(f"[exit] NEW object {payload['obj']} bt={payload['backtrace']}",
                      flush=True)
            elif ev == "EXIT-MAIN-MENU":
                print(f"\n[exit] *** EXIT TO MAIN MENU *** arg1={payload['arg1']}", flush=True)
                print(f"[exit] *** backtrace: {payload['backtrace']}", flush=True)
            elif ev == "watchdog":
                print(f"[exit] watchdog call #{payload['n']} bt={payload['backtrace']}",
                      flush=True)
            elif ev == "stats":
                for o in payload["objects"]:
                    frozen = "FROZEN" if o["min"] == o["max"] else "moving"
                    print(f"[exit] obj {o['obj']} reads={o['reads']} "
                          f"first={o['first']} last={o['last']} [{frozen}]", flush=True)
                print(f"[exit] watchdog calls={payload['watchdogCalls']} "
                      f"reset={payload['reset']}", flush=True)
        elif message.get("type") == "error":
            print("script error:", message.get("description", "")[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[exit] logging to {out_path}", flush=True)

    deadline = time.time() + args.timeout
    next_at = time.time() + 20
    try:
        while time.time() < deadline:
            if time.time() >= next_at:
                next_at = time.time() + args.interval
                script.exports_sync.stats()
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            script.exports_sync.stats()
        except Exception as exc:  # noqa: BLE001
            print(f"[exit] final stats failed: {exc}")
        session.detach()
        out.close()
    print(f"\n[exit] trace written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
