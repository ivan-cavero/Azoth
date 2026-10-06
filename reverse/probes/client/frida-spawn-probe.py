#!/usr/bin/env python3
"""Spawn-decision probe: watch record-1 through portrayal -> predicate -> create/delete.

Hooks (all read-only, no writes):
  FUN_141717fc0 entry: log record_id (u16 param_2).
  FUN_14178db00 (portrayal) entry: log key u64 at (param_2 + 0x20).
  FUN_146165f20 (predicate) : log key + return al (the decision bit).
  FUN_14178ec80 (creator) entry: log key + DAT_149e8f8b4 + DAT_149e8f68c flags.
  FUN_1417b45c0 (deleter) entry: log key being removed.

Attach AFTER NewWorld.exe exists; hooks persist for the world attempt.
Logs go to stdout and `.azoth/logs/spawn-probe.log`.
"""

from __future__ import annotations

import time
from pathlib import Path

import frida
from _paths import project_log

LOG = project_log("spawn-probe.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

let rec1 = 0, portray = 0, pred0 = 0, pred1 = 0, created = 0, deleted = 0;

function key8(p) {
  try { return p.readU64().toString(); } catch (e) { return 'err'; }
}

// record handler entry: (param_1, u16 record_id, param_3, param_4, param_5)
try {
  Interceptor.attach(at(0x141717fc0), {
    onEnter(args) {
      const id = args[1].toInt32() & 0xffff;
      if (id === 1) {
        rec1++;
        if (rec1 <= 12) send({ev: 'record1', n: rec1});
      }
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '717fc0', err: String(e).slice(0, 100)}); }

// portrayal entry: key = *(param_2 + 0x20)
try {
  Interceptor.attach(at(0x14178db00), {
    onEnter(args) {
      portray++;
      let k = '?';
      try { k = args[1].add(0x20).readU64().toString(); } catch (e) {}
      this.k = k;
      if (portray <= 30) send({ev: 'portray', n: portray, key: k});
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '78db00', err: String(e).slice(0, 100)}); }

// predicate: arg = &key, returns bool in al
try {
  Interceptor.attach(at(0x146165f20), {
    onEnter(args) {
      try { this.k = args[0].readU64().toString(); } catch (e) { this.k = '?'; }
    },
    onLeave(ret) {
      const al = ret.and(0xff).toInt32();
      if (al === 0) pred0++; else pred1++;
      if ((pred0 + pred1) <= 30) send({ev: 'pred', key: this.k, al: al});
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '6165f20', err: String(e).slice(0, 100)}); }

// creator entry: (param_1, key)
try {
  Interceptor.attach(at(0x14178ec80), {
    onEnter(args) {
      created++;
      const k = args[1].toString();
      let f1 = -1, f2 = -1;
      try {
        f1 = at(0x149e8f8b4).readU8();
        f2 = at(0x149e8f68c).readU8();
      } catch (e) {}
      if (created <= 20) send({ev: 'create', n: created, key: k, f8b4: f1, f68c: f2});
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '78ec80', err: String(e).slice(0, 100)}); }

// deleter entry: (param_1, key, ...)
try {
  Interceptor.attach(at(0x1417b45c0), {
    onEnter(args) {
      deleted++;
      if (deleted <= 20) send({ev: 'delete', n: deleted, key: args[1].toString()});
    }
  });
} catch (e) { send({ev: 'hook-fail', f: '7b45c0', err: String(e).slice(0, 100)}); }

setInterval(function () {
  send({ev: 'tick', rec1: rec1, portray: portray, pred0: pred0, pred1: pred1,
        created: created, deleted: deleted});
}, 5000);
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
    print("[probe] spawn-decision watch active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
