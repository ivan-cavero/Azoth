#!/usr/bin/env python3
"""Capture the size + leading bytes of every message that reaches the CSDK
stream reader (FUN_146b6eb70).

The client acks all 1306 of our datagrams yet only 4 messages ever reach
the typed-stream reader per session. This probe records, for each of those
4, the declared size and the first bytes, so they can be matched against
the replay bodies we sent (each replay body starts with a [00 01 <type>]
preamble). If the four are simply the first four replay messages, the
client stops consuming the stream after a fixed budget; if they are
scattered, the filter is by content (type id).

param_2 carries the size (func_0x0001409055d0(param_2));
param_4 is the reader (func_0x000140870bc0 copies out of it).
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const rva = (v) => v - 0x140000000;

const READER = base.add(rva(0x146b6eb70));
// size_of(param_2) as the client itself computes it
const SIZE_OF = new NativeFunction(base.add(rva(0x1409055d0)),
                                   'uint', ['pointer']);
// current read cursor inside the reader
const CURSOR = new NativeFunction(base.add(rva(0x140873230)),
                                   'pointer', ['pointer']);
// copy a reader's remaining bytes out (as the client does into auStack_e8)
const COPY = new NativeFunction(base.add(rva(0x140870bc0)),
                                'void', ['pointer', 'pointer']);

let n = 0;
Interceptor.attach(READER, {
  onEnter(args) {
    n++;
    const size = SIZE_OF(args[1]);
    const cur = CURSOR(args[3]);
    let head = null;
    let remaining = null;
    try {
      // The copy helper fills a small-string-like out buffer; give it a
      // 256-byte scratch and read back the length the client sees.
      const scratch = Memory.alloc(0x400);
      scratch.writeByteArray(new Uint8Array(0x400));
      COPY(scratch, args[3]);
      const p = scratch.readPointer();
      const len = scratch.add(8).readU32();
      remaining = len;
      const bytes = p.readByteArray(Math.min(len, 32));
      head = Array.from(new Uint8Array(bytes))
        .map((b) => b.toString(16).padStart(2, '0')).join(' ');
    } catch (e) {
      head = 'err:' + String(e);
    }
    send({ev: 'msg', n: n, size: size, cursor: cur.toString(),
          remaining: remaining, head: head});
  }
});
setInterval(function () { send({ev: 'total', n: n}); }, 3000);
send({ev: 'probe-ready'});
"""


def main() -> int:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)
    script.on("message", lambda m, _d: print(m.get("payload") or m, flush=True))
    script.load()
    print("[probe] CSDK stream reader armed (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
