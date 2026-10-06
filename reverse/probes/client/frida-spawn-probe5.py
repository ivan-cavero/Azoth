#!/usr/bin/env python3
"""Probe5: per-key fate through insert -> creator-table -> create/delete.

Hooks (read-only):
  FUN_141717fc0 entry: flag when record_id==1 (single-threaded, synchronous).
  FUN_1415e68b0 entry: log (isRec1, key u64 at (param_2?)) — signature
      (param_1, param_2=out?, param_3=key-ptr?, ...) — actually
      1415e68b0(param_1+0x578, &lStack_178, keyptr, ...) so key = *param_3.
      Log key + onLeave *param_2 (found flag: 0/1 at +1?).
      Simplest robust: log key; log whether node count grew (can't here).
      Instead log the OUT param qword at +0x58 (0 = miss/new, else found).
  FUN_1416bdf00 entry: log (isRec1, key param_2) + onLeave retval (0 = miss).
  FUN_14178ec80 entry: log (isRec1, key).
  FUN_1417b45c0 entry: log (isRec1, key).
  FUN_14178db00 entry: log (isRec1, key at param_2+0x20).

isRec1 correlation: flag set at record entry, consumed at the NEXT hook hit
(any of them), since handling is synchronous. Attribute generously: keep the
flag until a portray/insert for ANOTHER record would clear it — instead, stamp
every event with current record_id (last seen). Simpler and lossless.
"""

from __future__ import annotations

import time
from pathlib import Path

import frida
from _paths import project_log

LOG = project_log("spawn-probe5.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

let curRec = -1;
let counts = {};

function bump(k) { counts[k] = (counts[k] || 0) + 1; }
function ku(p) { try { return p.readU64().toString(); } catch (e) { return '?'; } }

function hook(va, name, cb) {
  try { Interceptor.attach(at(va), { onEnter(args) { cb(args, this); } }); }
  catch (e) { send({ev: 'hook-fail', f: name}); }
}

hook(0x141717fc0, 'rec', function (args) {
  curRec = args[1].toInt32() & 0xffff;
  bump('rec' + curRec);
});

// portrayal: key = *(param_2 + 0x20)
hook(0x14178db00, 'portray', function (args) {
  const k = ku(args[1].add(0x20));
  bump('portray');
  if (curRec === 1) send({ev: 'rec1-portray', key: k});
});

// 1415e68b0(param_1, out, keyptr, ...): key = *keyptr
hook(0x1415e68b0, 'insert', function (args) {
  bump('insert');
  if (curRec === 1) {
    let k = '?';
    try { k = args[2].readPointer().readU64().toString(); } catch (e) {}
    send({ev: 'rec1-insert', key: k});
  }
});

// 1416bdf00(param_1, key): returns ptr (0 = miss)
hook(0x1416bdf00, 'lookup', function (args) {
  this.rec = curRec;
  try { this.k = args[1].toString(); } catch (e) { this.k = '?'; }
  bump('lookup');
}, null);
try {
  Interceptor.attach(at(0x1416bdf00), {
    onEnter(args) {
      this.rec = curRec;
      try { this.k = args[1].toString(); } catch (e) { this.k = '?'; }
      bump('lookup');
    },
    onLeave(ret) {
      if (this.rec === 1) send({ev: 'rec1-lookup', key: this.k, hit: ret.isNull() ? 0 : 1});
    }
  });
} catch (e) { send({ev: 'hook-fail', f: 'lookup2'}); }

hook(0x14178ec80, 'create', function (args) {
  bump('create');
  if (curRec === 1) send({ev: 'rec1-create', key: args[1].toString()});
});
hook(0x1417b45c0, 'delete', function (args) {
  bump('delete');
  if (curRec === 1) send({ev: 'rec1-delete', key: args[1].toString()});
});

setInterval(function () {
  send({ev: 'tick', cur: curRec, counts: counts});
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
    print("[probe5] per-key fate watch active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
