#!/usr/bin/env python3
"""Page-level write watch around the manager to catch the +8 writer.

MemoryAccessMonitor on the exact 8 bytes returned only the gate's own read
and never fired a write, which is consistent with "nothing ever writes it"
but also with "the writer lives in another process image / a JIT region we
did not map". This widens the watch to the whole heap page the manager
lives on (4 KB, read+write) so any store into that page is reported with
its origin. It is noisy, but the manager page is small and almost all hits
should be the per-frame gate read; the first *write* from anywhere other
than the gate is the setter.
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;
const off = (p) => 'nw+' + p.sub(base).toString(16);
const GATE = base.add(rva(0x146800d10));

let mgr = null, page = null, armed = false, writes = 0, gate = 0;

Interceptor.attach(GATE, {
  onEnter(args) {
    gate++;
    if (mgr === null) { mgr = args[0]; arm(); }
  }
});

function arm() {
  if (armed) return;
  // 4 KB-aligned page containing mgr+8.
  const target = mgr.add(8);
  page = target.and(ptr('0xfffffffffffff000'));
  armed = true;
  send({ev: 'armed', page: page.toString(), mgr: mgr.toString()});
  try {
    MemoryAccessMonitor.enable([{ base: page, size: 0x1000 }], {
      onAccess: function (d) {
        const from = d.from ? off(d.from) : '?';
        if (d.operation === 'write') {
          writes++;
          if (writes <= 40) send({ev: 'WRITE', from: from, addr: off(d.address)});
        }
        return true;
      }
    });
  } catch (e) { send({ev: 'arm-error', err: String(e)}); }
}

setInterval(function () {
  if (mgr === null) return;
  send({ev: 'state', id: mgr.add(8).readU64().toString(), writes: writes, gate: gate});
}, 3000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] page write-watch armed (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
