#!/usr/bin/env python3
"""Probe3: who builds actors? copy-ctor / factory / op-dispatch + portrayal gate flags.

Hooks (read-only):
  FUN_14161b570 (actor copy-ctor): count + log param_2 (prototype) first qword.
  FUN_141563e20 (factory): count.
  FUN_1415d91b0 (op-dispatch): count + log op (param_1).
  FUN_1416957c0 (factory-wrap): count.
  FUN_14178ec80 (creator): count (bottom-loop reach).
  Tick: read DAT_149e8f688/68c/740/744 + DAT_14a435a40 (tick counter?).
"""

from __future__ import annotations

import time
from pathlib import Path

import frida
from _paths import project_log

LOG = project_log("spawn-probe3.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

let ctor = 0, factory = 0, wrap = 0, created = 0;
let ops = {};

function hook(va, name, cb) {
  try {
    Interceptor.attach(at(va), { onEnter(args) { cb(args); } });
  } catch (e) { send({ev: 'hook-fail', f: name}); }
}

hook(0x14161b570, 'ctor', function (args) {
  ctor++;
  let v0 = '?';
  try { v0 = args[1].readPointer().toString(); } catch (e) {}
  if (ctor <= 15) send({ev: 'ctor', n: ctor, proto_v0: v0});
});
hook(0x141563e20, 'factory', function () {
  factory++;
  if (factory <= 5) send({ev: 'factory', n: factory});
});
hook(0x1416957c0, 'wrap', function () {
  wrap++;
  send({ev: 'wrap', n: wrap});
});
hook(0x1415d91b0, 'opdispatch', function (args) {
  const op = args[0].toInt32();
  ops[op] = (ops[op] || 0) + 1;
});
hook(0x14178ec80, 'create', function (args) {
  created++;
  if (created <= 10) send({ev: 'create', n: created, key: args[1].toString()});
});

setInterval(function () {
  let f = {};
  try {
    f.f688 = at(0x149e8f688).readU8();
    f.f68c = at(0x149e8f68c).readU8();
    f.f740 = at(0x149e8f740).readU8();
    f.f744 = at(0x149e8f744).readU8();
    f.f8b0 = at(0x149e8f8b0).readU8();
    f.f8b4 = at(0x149e8f8b4).readU8();
  } catch (e) {}
  send({ev: 'tick', ctor: ctor, factory: factory, wrap: wrap, created: created, ops: ops, flags: f});
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
    print("[probe3] actor-creation watch active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
