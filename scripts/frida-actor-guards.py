#!/usr/bin/env python3
"""Which of the four guards kills the local-player actor?

Measured 2026-09-27: the record handler FUN_141717fc0 runs 283 times and the
parsed `interestId` ([rbp+0x268], written by the visitor registered at
0x14171800c) is 1 exactly 30 times. So the first guard

    141718247  cmp word ptr [rbp+0x268], 1
    14171824f  jne 0x141718398

passes. Three more guards stand between that and the actor build:

    141718255  <block start>                  reached when interestId == 1
    14171825c  mov rax, [r13+0x850]
    14171825f  call [rax+0x20]                "slot ready?"
    141718264  je 0x141718398                 -> skip
    14171826a  <after that call returned true>
    1417182a3  cmp qword ptr [rax], 0
    1417182a7  jne 0x141718398                -> skip
    1417182ad  <after that guard passed>
    1417182ce  call 0x146165ff0(obj, 3)       property/component lookup
    1417182d5  je 0x14171836d                 -> skip the actor build
    1417182db  <actor build: "newActorId">    the path we want
    14171836d  <skip path>

Counts each so the first one that stops firing is the culprit. Writes nothing.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const base = Process.findModuleByName('NewWorld.exe').base;
const at = (va) => base.add(va - 0x140000000);

const P = {
  interest_is_1: 0x141718255,
  slot_call:     0x14171825F,
  slot_true:     0x14171826A,
  guard3_pass:   0x1417182AD,
  prop_call:     0x1417182CE,
  actor_build:   0x1417182DB,
  skip_path:     0x14171836D,
};

const counts = {};
for (const k in P) counts[k] = 0;

for (const k in P) {
  try {
    Interceptor.attach(at(P[k]), (function (name) {
      return function () { counts[name]++; };
    })(k));
    send({ ev: 'hooked', at: k });
  } catch (e) {
    send({ ev: 'hook-error', at: k, err: String(e).slice(0, 90) });
  }
}

// The property lookup the 4th guard depends on.
try {
  Interceptor.attach(at(0x146165FF0), {
    onEnter(args) { this.obj = args[0].toString(); this.id = args[1].toInt32(); },
    onLeave(ret) {
      counts.prop_lookup = (counts.prop_lookup || 0) + 1;
      const r = ret.toInt32();
      counts['prop_ret_' + (r === 0 ? 'zero' : 'nonzero')] =
        (counts['prop_ret_' + (r === 0 ? 'zero' : 'nonzero')] || 0) + 1;
      if (counts.prop_lookup <= 10) {
        send({ ev: 'PROP', obj: this.obj, id: this.id, ret: r });
      }
    },
  });
  send({ ev: 'hooked', at: 'prop_lookup' });
} catch (e) {
  send({ ev: 'hook-error', at: 'prop_lookup', err: String(e).slice(0, 90) });
}

setInterval(function () { send({ ev: 'counts', counts: counts }); }, 10000);
send({ ev: 'ready' });
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] actor-guard observer active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())