#!/usr/bin/env python3
"""Read the client's OWN in-game time, by running the client's own console command.

WHY THIS EXISTS
===============
The server sends `TimeComponentClientFacet_SyncTimeChange` (wire 0x1096) and `SyncDayPhase`
(0x1097) in answer to the client's `TimeComponentServerFacet_SyncToClient` (0x1098). Today those
two bodies are the CAPTURED ones, re-sent verbatim, so the client receives the same time values
for the whole session. Whether that freezes the in-game clock is a question nothing in this
repository could measure - until now.

THE INSTRUMENT, DERIVED RATHER THAN GUESSED
===========================================
The client registers its console commands with a uniform shape, read off the binary at the
`nw_getPlayerPosition` site (documented at 0x1410352a1) and reproduced at `lc_getTime`:

    lea rdx, [rip+name]         ; 1st arg: the command name
    lea r8,  [rip+handler]      ; 2nd arg: the handler
    xor r9d, r9d                ; 3rd arg: 0
    lea rcx, [rip+description]  ; 4th arg: the description string
    mov rcx, r10                ; this
    call [rax+0x110]            ; register(name, handler, 0, description)

`reverse/tools/find-rip-lea.py --string <name>` finds the registration site and the handler is the
`lea r8` two instructions above it. Calibrated: `nw_getPlayerPosition` -> handler 0x141015b30,
which is the address this repository already recorded by hand. Applying the same rule:

    lc_getTime     handler 0x141015E80   description "Print current game time."
    lc_requestTime handler 0x141018E10   description "force sync time with the server."

`lc_getTime` prints through the SAME printer the position command uses (`FUN_141022A90`),
and the format string at 0x147fd2b20 is

    Current Container Time: %s:%s:%s; t = %s;  CryTime:  %s:%s; DayPhase: %s

with SEVEN string pointers as arguments (the handler converts the numbers to decimal first, which
is why the format is `%s`). So hooking that printer and calling the handler yields the client's
own hour, minute, second, `t`, two CryTime values and the day phase, as text.

Read-only with respect to game state: `lc_getTime` only prints. `--request` additionally runs
`lc_requestTime`, which makes the client send a real time-sync request to the server - the same
wire message (0x1098) the server's dispatcher already keys on.

Usage:
  python az.py probe frida-game-time --timeout 120 --poll 5
  python az.py probe frida-game-time --request          # also press the client to ask the server
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from _paths import probe_capture, safe_shutdown

# Console-command handlers, derived by the registration-shape rule above (see the docstring).
GET_TIME = 0x141015E80      # lc_getTime
REQUEST_TIME = 0x141018E10  # lc_requestTime
PRINTER = 0x141022A90       # FUN_141022a90(fmt, s1..s7) - the same printer nw_getPlayerPosition uses
FMT_TIME = 0x147FD2B20      # "Current Container Time: %s:%s:%s; t = %s;  CryTime:  %s:%s; DayPhase: %s"

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let prints = 0;
  let last = null;

  function cstr(p) {
    if (p === null || p.isNull()) return null;
    try { return p.readUtf8String(); } catch (e) { return '<unreadable>'; }
  }

  try {
    Interceptor.attach(rva(0x141022a90), {
      onEnter(args) {
        prints++;
        // The handler passes the 7 decimal strings as pointers, in the format's order:
        // hour, minute, second, t, cryHour, cryMinute, dayPhase.
        const vals = [];
        for (let i = 1; i <= 7; i++) { vals.push(cstr(args[i])); }
        last = {
          fmt: cstr(args[0]),
          vals: vals,
          t: Date.now(),
        };
        send({ ev: 'print', vals: vals });
      },
    });
  } catch (e) { send({ ev: 'error', hook: 'printer', error: String(e) }); }

  rpc.exports = {
    sample(request) {
      const before = prints;
      let error = null;
      try {
        const fn = new NativeFunction(rva(0x141015e80), 'void', []);
        fn();
      } catch (e) { error = String(e); }
      let requested = false;
      if (request) {
        try {
          const rq = new NativeFunction(rva(0x141018e10), 'void', []);
          rq();
          requested = true;
        } catch (e) { error = (error ? error + '; ' : '') + 'request: ' + String(e); }
      }
      return {
        prints_before: before,
        prints_after: prints,
        printed: last,
        requested: requested,
        error: error,
      };
    },
    counters() { return { prints: prints }; },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--request", action="store_true",
                    help="also run lc_requestTime, so the client asks the server for the time")
    ap.add_argument("--keep-process", action="store_true",
                    help="leave the client running on exit (orderly detach) instead of ending it")
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[gt]", json.dumps(m)[:300], flush=True))
    script.load()
    print(f"[gt] attached to {args.process}", flush=True)

    capture = probe_capture(f"game-time-{int(time.time())}.jsonl")
    print(f"[gt] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    first = None
    while time.time() < end:
        try:
            res = script.exports_sync.sample(args.request)
        except Exception as exc:  # noqa: BLE001
            print(f"[gt] rpc failed: {exc}", flush=True)
            break
        printed = res.get("printed") or {}
        vals = printed.get("vals")
        if vals and first is None:
            first = vals
        stamp = time.strftime("%H:%M:%S", time.localtime(time.time()))
        print(f"[gt] {stamp} h:m:s={vals[0] if vals else None}:{vals[1] if vals else None}:"
              f"{vals[2] if vals else None} t={vals[3] if vals else None} "
              f"cry={vals[4] if vals else None}:{vals[5] if vals else None} "
              f"dayPhase={vals[6] if vals else None} prints={res.get('prints_after')}"
              f"{' REQUESTED' if res.get('requested') else ''}"
              f"{' err=' + res['error'] if res.get('error') else ''}", flush=True)
        with capture.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time(), **res}) + "\n")
        if time.time() + args.poll > end:
            break
        time.sleep(args.poll)

    try:
        last = script.exports_sync.sample(False).get("printed") or {}
    except Exception:  # noqa: BLE001
        last = {}
    lv = last.get("vals")
    if first and lv:
        print(f"[gt] first={first}  last={lv}", flush=True)
        print(f"[gt] CLOCK ADVANCED={first != lv}  (h:m:s {first[0]}:{first[1]}:{first[2]} -> "
              f"{lv[0]}:{lv[1]}:{lv[2]}; dayPhase {first[6]} -> {lv[6]})", flush=True)
    strategy = safe_shutdown(session, script, kill=not args.keep_process, device=device)
    print(f"[gt] shutdown strategy: {strategy}", flush=True)
    print(f"[gt] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
