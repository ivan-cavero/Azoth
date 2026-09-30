#!/usr/bin/env python3
"""Correlate record-1 with its portrayal key + predicate + downstream path.

Single-threaded sequential logic: FUN_141717fc0 calls portrayal synchronously,
so a flag set at record-1 entry identifies the portray call for record 1.

Also logs:
  DAT_149e8f688 / 68c / 740 / 744 gate flags at each record-1 portray.
  Whether the bottom loop in portrayal runs (hook 14178ec80 already covers it;
  here we count (param_1+0x30) list length at portray time for record 1).
  FUN_1415e68b0 result (the table lookup): log *out param (found/not-found).
"""

from __future__ import annotations

import time
from pathlib import Path

import frida

LOG = Path(r"C:\Users\ivang\AppData\Local\Temp\azoth-spawn-probe2.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

let wantRec1 = false;
let rec1n = 0;

try {
  Interceptor.attach(at(0x141717fc0), {
    onEnter(args) {
      const id = args[1].toInt32() & 0xffff;
      wantRec1 = (id === 1);
      if (wantRec1) rec1n++;
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '717fc0'}); }

// portrayal entry: key = *(param_2 + 0x20); count (param_1+0x30) list length
try {
  Interceptor.attach(at(0x14178db00), {
    onEnter(args) {
      if (!wantRec1) return;
      wantRec1 = false;
      let k = '?';
      try { k = args[1].add(0x20).readU64().toString(); } catch (e) {}
      let flags = {};
      try {
        flags.f688 = at(0x149e8f688).readU8();
        flags.f68c = at(0x149e8f68c).readU8();
        flags.f740 = at(0x149e8f740).readU8();
        flags.f744 = at(0x149e8f744).readU8();
      } catch (e) {}
      // walk (param_1+0x30) intrusive list, count nodes, sample node[2] keys + node[3]+0x15b bytes
      let nodes = -1;
      let sample = [];
      try {
        const head = args[0].add(0x30);
        let cur = head.readPointer();
        nodes = 0;
        while (!cur.isNull() && !cur.equals(head) && nodes < 200) {
          nodes++;
          try {
            const nk = cur.add(0x10).readU64().toString();
            const holder = cur.add(0x18).readPointer();
            let b = -1;
            try { b = holder.add(0x15b).readU8(); } catch (e) {}
            if (sample.length < 8) sample.push({key: nk, b15b: b});
          } catch (e) {}
          try { cur = cur.readPointer(); } catch (e) { break; }
        }
      } catch (e) { nodes = -2; }
      send({ev: 'rec1-portray', n: rec1n, key: k, flags: flags, nodes: nodes, sample: sample});
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '78db00'}); }

// predicate result for record-1 keys: reuse flag with 1-call delay? Instead log all pred with al==0 and small sample of al==1.
let p0 = 0, p1 = 0;
try {
  Interceptor.attach(at(0x146165f20), {
    onEnter(args) {
      try { this.k = args[0].readU64().toString(); } catch (e) { this.k = '?'; }
      this.rec = wantRec1;
    },
    onLeave(ret) {
      const al = ret.and(0xff).toInt32();
      if (this.rec) {
        send({ev: 'rec1-pred', n: rec1n, key: this.k, al: al});
        wantRec1 = false;
      } else {
        if (al === 0) { p0++; if (p0 <= 10) send({ev: 'pred0', key: this.k}); }
        else { p1++; }
      }
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '6165f20'}); }

// creator / deleter with keys
try {
  Interceptor.attach(at(0x14178ec80), {
    onEnter(args) { send({ev: 'create', key: args[1].toString()}); }
  });
} catch (e) {}
try {
  Interceptor.attach(at(0x1417b45c0), {
    onEnter(args) { send({ev: 'delete', key: args[1].toString()}); }
  });
} catch (e) {}

setInterval(function () {
  send({ev: 'tick', rec1n: rec1n, p0: p0, p1: p1});
}, 8000);
send({ev: 'ready'});
"""


def main() -> int:
    logf = LOG.open("a", encoding="utf-8")
    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS)

    def on_msg(m, _d):
        p = m.get("payload")
        line = str(p) if p is None else (
            __import__("json").dumps(p) if isinstance(p, dict) else str(p)
        )
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    script.on("message", on_msg)
    script.load()
    print("[probe2] record-1 correlation active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
