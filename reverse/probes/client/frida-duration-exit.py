#!/usr/bin/env python3
"""Catch WHAT ARMS the long-session teardown, with a backtrace per anchor.

WHY. Sessions end by the client's own graceful `SM_DISCONNECT` (system record id 3)
after a while - measured once at **1 h 06 min 33 s** after spawn (2026-10-14) and
reproduced today. The 20-minute variant of the same path was traced to a QUEUED
delegate (`FUN_141004100` <- `FUN_14107fb40` <- per-frame scheduler), so the decision
is made somewhere else and queued - which is why no xref finds it. The open question
is which of the two known entry points runs at the long deadline:

  * the queued delegate chain (the 20-minute path), or
  * the per-state activity watchdog `FUN_146445e10`, whose return 1 forces
    `FUN_14643e4a0` to send a disconnect notice with a state-derived reason.

Both are hooked here, together with the two log anchors, and every hit carries a
backtrace and the client's own QPC clock. The watchdog is hooked on ENTER but only
reported on LEAVE when it actually returns non-zero, so a per-frame call site does
not flood the channel.

Read-only. Private no-EAC client; Steam untouched.

Usage:
  python az.py probe frida-duration-exit --timeout 3600
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

ANCHORS = {
    0x146420610: "ActorContainerDisconnect",
    0x146444B10: "exit-to-main-menu",
    0x141004100: "queued-teardown-delegate",
    0x146460240: "disconnect-notice-sender",
}

WATCHDOG = 0x146445E10

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const nowFn = new NativeFunction(rva(0x141413890), 'uint64', []);
  const anchors = %ANCHORS%;

  const bt = (ctx) => {
    try {
      return Thread.backtrace(ctx, Backtracer.ACCURATE)
        .map(a => a.sub(base).toString(16)).slice(0, 14);
    } catch (e) { return ['bt-fail']; }
  };

  for (const [addr, label] of anchors) {
    try {
      Interceptor.attach(rva(addr), {
        onEnter(args) {
          send({
            ev: 'anchor', label: label, addr: addr.toString(16),
            now: nowFn().toString(),
            a0: args[0].toString(), a1: args[1].toString(), a2: args[2].toString(),
            bt: bt(this.context),
          });
        }
      });
    } catch (e) {
      send({ ev: 'attach-error', label: label, error: String(e) });
    }
  }

  // The per-state watchdog: report ONLY when it returns non-zero (forces a disconnect).
  try {
    Interceptor.attach(rva(%WATCHDOG%), {
      onEnter(args) {
        this.state = args[0].toString();
        this.expected = args[1].toString();
      },
      onLeave(ret) {
        const v = ret.toInt32() & 0xff;
        if (v === 0) return;
        send({
          ev: 'watchdog-timeout', label: 'ingame-watchdog', addr: (%WATCHDOG%).toString(16),
          now: nowFn().toString(), state: this.state, expected: this.expected,
          ret: v, bt: bt(this.context),
        });
      }
    });
  } catch (e) {
    send({ ev: 'attach-error', label: 'ingame-watchdog', error: String(e) });
  }

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
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--wait", type=int, default=60)
    args = ap.parse_args()

    device = frida.get_local_device()
    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[duration] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    pairs = ", ".join(f"[{a}, {json.dumps(l)}]" for a, l in ANCHORS.items())
    source = JS.replace("%ANCHORS%", f"[{pairs}]").replace("%WATCHDOG%", hex(WATCHDOG))
    script = session.create_script(source)

    out = Path(__file__).resolve().parents[2] / "sessions" / f"duration-exit-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")
    seen: dict[str, int] = {}

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            label = payload.get("label", payload.get("ev"))
            seen[label] = seen.get(label, 0) + 1
            if label in ("ActorContainerDisconnect", "exit-to-main-menu",
                         "watchdog-timeout", "queued-teardown-delegate"):
                print(f"[duration] {json.dumps(payload)[:900]}", flush=True)
            elif seen[label] <= 2:
                print(f"[duration] {json.dumps(payload)[:400]}", flush=True)
        else:
            print("[duration] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[duration] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(30)
            print(f"[duration] counts {json.dumps(seen)}", flush=True)
    except KeyboardInterrupt:
        pass

    # This probe hooks a hot function: end the process deliberately rather than
    # detaching, which is the measured execute-after-unload crash signature.
    try:
        script.unload()
    except Exception:
        pass
    try:
        device.kill(pid)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
