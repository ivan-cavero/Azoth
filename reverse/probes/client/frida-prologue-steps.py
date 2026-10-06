#!/usr/bin/env python3
"""Resolve the contradiction: is 0x141718034 inside FUN_141717fc0 ever reached?

Measured 2026-09-27:
  * hooking FUN_141717fc0 entry -> 283 calls, record ids 1..94 (id 1 thirty times)
  * hooking 0x141718034 (straight-line code inside that same function, right
    after the "interestId" deserialize call) -> 0 calls

Those cannot both be true, so this probe hooks every step of the prologue and
the first deserialize, and counts each:

  0x141717FC0  function entry
  0x141717FDF  lea rbp, [rsp-0x220]        (frame set up)
  0x141718028  lea rcx, [rbp+0x1a8]        (just before the call)
  0x14171802F  call 0x146189770            (the "interestId" deserialize)
  0x141718034  mov [rbp+0x1b0], al         (right after it)
  0x146189770  the deserialize helper itself

Writes nothing.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const base = Process.findModuleByName('NewWorld.exe').base;
const at = (va) => base.add(va - 0x140000000);

const STEPS = {
  entry:        0x141717FC0,
  frame:        0x141717FDF,
  before_call:  0x141718028,
  call_site:    0x14171802F,
  after_call:   0x141718034,
  helper:       0x146189770,
};

const counts = {};
for (const k in STEPS) counts[k] = 0;
// interestId values seen right after the deserialize at 0x14171802f
const interest = {};
const ctxid = {};

for (const k in STEPS) {
  try {
    const b = Array.from(new Uint8Array(at(STEPS[k]).readByteArray(4)))
      .map((x) => x.toString(16).padStart(2, '0')).join(' ');
    Interceptor.attach(at(STEPS[k]), (function (name) {
      return function () {
        counts[name]++;
        if (name === 'after_call') {
          // [rbp+0x268] was just written by the "interestId" visitor
          try {
            const v = this.context.rbp.add(0x268).readU16();
            interest[v] = (interest[v] || 0) + 1;
          } catch (e) { interest['err'] = (interest['err'] || 0) + 1; }
        }
      };
    })(k));
    send({ ev: 'hooked', at: k, bytes: b });
  } catch (e) {
    send({ ev: 'hook-error', at: k, err: String(e).slice(0, 90) });
  }
}

setInterval(function () {
  send({ ev: 'counts', counts: counts, interestId: interest, clientContextId: ctxid });
}, 10000);
send({ ev: 'ready' });
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] prologue-step observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())