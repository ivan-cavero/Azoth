#!/usr/bin/env python3
"""Probe4: catch the 13 world actors being built + record-1's fate.

Hooks (read-only):
  FUN_14161b9b0 (default prototype ctor, sets vtable 0x148033f90): count.
  FUN_1415e68b0 (portrayal table insert/lookup): count + found flag.
  FUN_1415e4740 (table node insert): count.
  FUN_1417ab0d0 (link existing): count.
  FUN_14172ce70 (record merge): count.
  FUN_14178db00 portrayal: count + record-1-correlated keys (flag method).
  FUN_141717fc0: set flag when record_id==1.
"""

from __future__ import annotations

import time
from pathlib import Path

import frida
from _paths import project_log

LOG = project_log("spawn-probe4.log")

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);

let proto = 0, insert = 0, nodeIns = 0, link = 0, merge = 0, portray = 0, rec1 = 0;
let wantRec1 = false;

function hook(va, name, cb) {
  try { Interceptor.attach(at(va), { onEnter(args) { cb(args); } }); }
  catch (e) { send({ev: 'hook-fail', f: name}); }
}

hook(0x141717fc0, 'rec', function (args) {
  const id = args[1].toInt32() & 0xffff;
  wantRec1 = (id === 1);
  if (wantRec1) { rec1++; if (rec1 <= 5) send({ev: 'record1', n: rec1}); }
});
hook(0x14161b9b0, 'proto', function () {
  proto++;
  if (proto <= 20) send({ev: 'proto', n: proto});
});
hook(0x1415e68b0, 'insert', function () {
  insert++;
});
hook(0x1415e4740, 'nodeins', function () {
  nodeIns++;
});
hook(0x1417ab0d0, 'link', function (args) {
  link++;
  if (link <= 20) send({ev: 'link', n: link});
});
hook(0x14172ce70, 'merge', function () {
  merge++;
});
hook(0x14178db00, 'portray', function (args) {
  portray++;
  if (wantRec1) {
    wantRec1 = false;
    let k = '?';
    try { k = args[1].add(0x20).readU64().toString(); } catch (e) {}
    send({ev: 'rec1-portray', n: rec1, key: k, odd: (BigInt(k) & 1n).toString(),
          high32zero: (BigInt(k) >> 32n) === 0n ? '1' : '0'});
  }
});

setInterval(function () {
  send({ev: 'tick', rec1: rec1, portray: portray, proto: proto, insert: insert,
        nodeIns: nodeIns, link: link, merge: merge});
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
    print("[probe4] actor-build watch active", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
