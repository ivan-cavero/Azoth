#!/usr/bin/env python3
"""Hook the replica-bundle handler chain live (Frida, our runtime).

FUN_146a6b8e0 = handler that registers replicas + unmarshals the world
bundle (the r37 payload shape). FUN_146a6eac0 = the typed-stream dispatch
loop. FUN_1461ac120 = preamble reader. If the handler never fires during
InGame, the dispatch never reaches it (handler unbound / type filtered).
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const off = (p) => 'nw+' + p.sub(base).toString(16);

const H = {
  handler: base.add(0x146a6b8e0 - 0x140000000),
  dispatchLoop: base.add(0x146a6eac0 - 0x140000000),
  preamble: base.add(0x1461ac120 - 0x140000000),
  unmarshalBody: base.add(0x1461ac8d0 - 0x140000000),
};

let counts = {handler: 0, dispatchLoop: 0, preamble: 0, unmarshalBody: 0};
let lastReport = 0;

for (const [name, addr] of Object.entries(H)) {
  (function (n, a) {
    Interceptor.attach(a, {
      onEnter(args) {
        counts[n]++;
        const now = Date.now();
        if (n === 'handler' && counts.handler <= 3) {
          send({ev: 'handler-called', param2: args[1].toString(),
                firstArgs: args[2].toString()});
        }
        if (n === 'dispatchLoop' && counts.dispatchLoop <= 3) {
          send({ev: 'dispatch-called', count: args[2].toInt32()});
        }
      }
    });
  })(name, addr);
}

setInterval(function () {
  send({ev: 'counts', ...counts});
}, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] hooks on replica dispatch chain (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
