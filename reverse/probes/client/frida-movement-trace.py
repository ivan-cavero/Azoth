#!/usr/bin/env python3
"""Trace where a held W stops on its way to moving the local player.

WHY. Movement is the last open goal. Established facts: the keyboard reaches the
input dispatcher, the camera rotates, the UI consumes keys, and W produces no
movement and no outbound delta. The local player's entity has no physics/rigidbody
component, the prefab does not ship one, and the function that would build the
movable body (FUN_141763b70) never runs after process startup. What is NOT known is
WHERE in the client the W event stops: at an input filter, at a movement
interaction that was never started, or at a missing physics body.

This probe logs, in order, every stage of that path when W is held, so the first
stage that stays silent names the blocker. Read-only: it only attaches
Interceptor hooks and logs.

Stages hooked (all image-base relative, build 8654f01d):
  0x1449d5ec0  input event dispatcher (the W event is known to reach here)
  0x147135060  WM_INPUT window procedure (case 0xff path)
  0x141763b70  the transform/movable-body gate (creates GameTransformComponent)
  0x141582430  GameTransformComponent creator (only called by the gate)
  0x146af20d0  state-bundle reader (server record path)
  0x146af2340  per-fragment reader (server component path)
  0x146b6f190  typed-message dispatcher (InGame activity clock)

Usage:
  python ef.py probe frida-movement-trace [--timeout 240]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from _paths import probe_capture

HOOKS = (
    ("input-dispatch", 0x1449D5EC0),
    ("wm-input", 0x147135060),
    ("body-gate", 0x141763B70),
    ("transform-create", 0x141582430),
    ("bundle-reader", 0x146AF20D0),
    ("fragment-reader", 0x146AF2340),
    ("typed-dispatch", 0x146B6F190),
)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  const counts = {};
  for (const [name, va] of %HOOKS%) {
    counts[name] = 0;
    try {
      Interceptor.attach(off(va), {
        onEnter(args) {
          counts[name]++;
          // Log the first few of each so a repeating stage does not flood.
          if (counts[name] <= 12) {
            let extra = '';
            try {
              // For the bundle/fragment readers the first arg is the reader
              // object; log a couple of its pointers so the caller can be
              // correlated with the server-side record.
              extra = 'a0=' + args[0] + ' a1=' + args[1] + ' a2=' + args[2];
            } catch (e) { extra = ''; }
            send({ev:'hit', name: name, n: counts[name], extra: extra});
          }
        }
      });
    } catch (e) {
      send({ev:'hook-fail', name: name, msg: String(e)});
    }
  }
  // Periodic summary so a stage that stays at zero is visible without waiting
  // for the process to exit.
  setInterval(function () {
    send({ev:'summary', counts: counts});
  }, 5000);
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--out", default="movement-trace.jsonl")
    args = parser.parse_args()

    out_path = probe_capture(args.out)
    device = frida.get_local_device()
    session = None
    for _ in range(60):
        try:
            session = device.attach("NewWorld.exe")
            break
        except Exception:
            time.sleep(2)
    if session is None:
        raise SystemExit("could not attach to NewWorld.exe")

    script = session.create_script(JS.replace("%HOOKS%", json.dumps(list(HOOKS))))
    handle = out_path.open("w", encoding="utf-8")
    hits: dict[str, int] = {}

    def on_message(message, _data):
        if message.get("type") != "send":
            handle.write(json.dumps({"raw": message}) + "\n")
            handle.flush()
            return
        payload = message.get("payload") or {}
        event = payload.get("ev")
        if event == "hit":
            hits[payload["name"]] = payload["n"]
        handle.write(json.dumps(payload) + "\n")
        handle.flush()

    script.on("message", on_message)
    script.load()
    print(f"attached; logging to {out_path} for {args.timeout:.0f}s")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(5)
    try:
        session.detach()
    except Exception:
        pass
    handle.close()
    print("final hits per stage:", hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
