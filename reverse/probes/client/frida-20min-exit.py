#!/usr/bin/env python3
"""Catch the caller of the 20-minute self-exit, with a backtrace.

WHY. A private session ends by itself at **exactly 20:00 after the player spawns**
(measured 20:00, 20:01, 20:01, 20:02, 20:00 across five runs) and it ends *cleanly*:
`CGame::ActorContainerDisconnect` -> `CGame exiting to main menu` -> `Cleanup()`,
with `transportError` 0 and `OnLocalNetworkConnectionWarning` 0. That is the single
largest remaining stability problem, and the trigger is not visible statically:
`FUN_146444b10` ("CGame exiting to main menu") has **no direct callers**, and
`FUN_146420610` (`CGame::ActorContainerDisconnect`, the routine that logs the first
line of the sequence) is reached from a delegate/virtual dispatch.

The exact log string for the disconnect is `CGame::ActorContainerDisconnect`
(0x1484fd180) and the only function that references it is `FUN_146420610`, so that
function is the anchor: whatever calls it *is* the 20-minute decision.

This probe hooks the anchors and prints a **backtrace plus the client's own clock**
for each hit, converting an unreachable-by-xref decision into an ordered call chain:

  * `FUN_146420610`  -- CGame::ActorContainerDisconnect (the anchor)
  * `FUN_146444b10`  -- "CGame exiting to main menu"
  * `FUN_146445e10`  -- the InGame activity watchdog (known to force a disconnect
                       when its budget is spent)
  * `FUN_14486c740`  -- per-frame reader of `obj+0xAA8` ("time since last response")

Read-only. Private no-EAC client; Steam untouched.

Usage:
  python ef.py probe frida-20min-exit --timeout 1800
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
    0x146445E10: "ingame-watchdog",
    0x14486C740: "perframe-aa8-reader",
}

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const nowFn = new NativeFunction(rva(0x141413890), 'uint64', []);
  const anchors = %ANCHORS%;

  for (const [addr, label] of anchors) {
    try {
      Interceptor.attach(rva(addr), {
        onEnter(args) {
          let bt = [];
          try {
            bt = Thread.backtrace(this.context, Backtracer.ACCURATE)
                     .map(a => a.sub(base).toString(16));
          } catch (e) { bt = ['bt-fail']; }
          send({
            ev: 'anchor',
            label: label,
            addr: addr.toString(16),
            now: nowFn().toString(),
            arg0: args[0].toString(),
            bt: bt.slice(0, 12),
          });
        }
      });
    } catch (e) {
      send({ ev: 'attach-error', label: label, error: String(e) });
    }
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
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--wait", type=int, default=120)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[exit] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    pairs = ", ".join(f"[{a}, {json.dumps(l)}]" for a, l in ANCHORS.items())
    script = session.create_script(JS.replace("%ANCHORS%", f"[{pairs}]"))

    out = Path(__file__).resolve().parents[2] / "sessions" / f"exit-bt-{int(time.time())}.jsonl"
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
            if label in ("ActorContainerDisconnect", "exit-to-main-menu") or seen[label] <= 2:
                print(f"[exit] {json.dumps(payload)[:600]}", flush=True)
        else:
            print("[exit] err:", str(m.get("description"))[:200], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[exit] live -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(30)
            print(f"[exit] counts {json.dumps(seen)}", flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
