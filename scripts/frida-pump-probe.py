#!/usr/bin/env python3
"""Count typed-stream pump activity (Frida, our runtime).

146b08500 = dispatch wrapper (vtable 0x1485848b8 slot). If it never fires
while the client receives ch0 data, the Carrier->typed-stream bridge is
not wired: the client gets the bytes but nothing pumps them into the
replica dispatcher.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const off = (p) => 'nw+' + p.sub(base).toString(16);

const PUMP = base.add(0x146b08500 - 0x140000000);
const PREAMBLE = base.add(0x1461ac120 - 0x140000000);
const UNMARSHAL = base.add(0x1461ac8d0 - 0x140000000);
const BUNDLE = base.add(0x146a6b8e0 - 0x140000000);

let c = {pump: 0, preamble: 0, unmarshal: 0, bundle: 0};
for (const [n, a] of Object.entries({pump: PUMP, preamble: PREAMBLE,
                                     unmarshal: UNMARSHAL, bundle: BUNDLE})) {
  (function (name) {
    Interceptor.attach(a, {onEnter() { c[name]++; }});
  })(n);
}
setInterval(function () { send({ev: 'counts', ...c}); }, 2000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] pump counters (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
