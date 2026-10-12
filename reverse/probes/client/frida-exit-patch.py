#!/usr/bin/env python3
"""Neutralize the client's 20-minute self-exit and watch whether the session holds.

WHY. `frida-20min-exit` caught the clean self-exit with a full backtrace:

    CGame::ActorContainerDisconnect  FUN_146420610
      <- FUN_141004100   (a queued AZStd::delegate; action 1 or 2)
      <- FUN_14107fb40   (deferred-action queue drain)
      <- FUN_14147e7c0   (per-frame scheduler, QueryPerformanceCounter)
      <- FUN_1471586e0 <- FUN_146dbd0df <- FUN_14646c720 <- FUN_14646d3ac
      <- FUN_1410443a0

The delegate's whole disconnect body is one 5-byte `call` at **0x141004230**
(`e8 db c3 41 05` -> 0x146420610). The trigger is not visible statically: the
delegate is queued from a dispatch nothing points at, and the event is exactly
20:00 after `player spawn succeeds` across five runs.

This probe is the causal test, not a diagnosis: it NOPs that call and then watches
(1) whether the client is still in the world past 20 minutes, and (2) whether it
crash-stops instead. Both are informative; a crash means the teardown is load
bearing and the trigger has to be removed upstream instead.

It also records the two instruments that must agree with any claim about this:
the per-frame `+0xAA8` "time since last response" value (the HUD icon) and the
InGame watchdog's own log cadence.

Write scope: five bytes of the private client's in-memory `.text`. The file on disk
is untouched, `python scripts/patch-dtls-disk.py restore` still restores everything,
and Steam is never involved. EAC is not present in this client.

Usage:
  python az.py probe frida-exit-patch --timeout 1800
  python az.py probe frida-exit-patch --no-patch --timeout 1800   # control
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

CALL_VA = 0x141004230          # call CGame::ActorContainerDisconnect
DELEGATE_VA = 0x141004100      # the queued delegate that makes the exit decision
WATCHDOG_VA = 0x146445E10      # InGame activity watchdog
PERFRAME_VA = 0x14486C740      # per-frame reader of conn+0xAA8
NOW_VA = 0x141413890

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const nowFn = new NativeFunction(rva(0x141413890), 'uint64', []);

  if (%PATCH%) {
    try {
      const site = rva(0x141004230);
      // .text is read+execute; a raw write faults (measured: access violation).
      // Re-protect the page, write, then restore the original protection.
      const before = Array.from(new Uint8Array(site.readByteArray(5)))
                          .map(b => b.toString(16).padStart(2, '0')).join('');
      Memory.protect(site, 0x1000, 'rwx');
      site.writeByteArray([0x90, 0x90, 0x90, 0x90, 0x90]);
      Memory.protect(site, 0x1000, 'r-x');
      const after = Array.from(new Uint8Array(site.readByteArray(5)))
                         .map(b => b.toString(16).padStart(2, '0')).join('');
      send({ ev: 'patched', site: '141004230', before: before, after: after });
    } catch (e) {
      send({ ev: 'patch-error', error: String(e) });
    }
  } else {
    send({ ev: 'control', note: 'not patchanted (--no-patch)' });
  }

  Interceptor.attach(rva(0x141004100), {
    onEnter(args) {
      let action = null;
      try { action = args[0].readS32(); } catch (e) {}
      send({ ev: 'delegate', now: nowFn().toString(), action: action });
    }
  });

  Interceptor.attach(rva(0x146445e10), {
    onEnter(args) {
      this.conn = args[0];
      this.before = null;
      try { this.before = args[0].add(0x1c).readS32(); } catch (e) {}
    }
  });

  let obj = null;
  Interceptor.attach(rva(0x14486c740), {
    onEnter(args) {
      if (obj === null && !args[0].isNull()) obj = args[0];
    }
  });

  rpc.exports = {
    status() {
      let field = null, age = null;
      if (obj !== null) {
        try {
          field = obj.add(0xaa8).readU64();
          age = nowFn().sub(field).toNumber();
        } catch (e) {}
      }
      return { obj: obj === null ? null : obj.toString(), field: field === null ? null : field.toString(),
               age_ms: age };
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
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--poll", type=float, default=60.0)
    ap.add_argument("--no-patch", action="store_true")
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[exitpatch] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS.replace("%PATCH%", "false" if args.no_patch else "true"))

    out = Path(__file__).resolve().parents[2] / "sessions" / f"exit-patch-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[exitpatch] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[exitpatch] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[exitpatch] live -> {out}", flush=True)

    end = time.time() + args.timeout
    last = None
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
            except Exception as exc:  # noqa: BLE001
                print("[exitpatch] status error:", exc, flush=True)
                maybe = find_game_pid()
                if maybe is None:
                    print("[exitpatch] the process is GONE", flush=True)
                    break
                continue
            age = st.get("age_ms")
            print(f"[exitpatch] aa8_age_ms={age}", flush=True)
            last = age
    except KeyboardInterrupt:
        pass
    print(f"[exitpatch] final aa8_age_ms={last}", flush=True)
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
