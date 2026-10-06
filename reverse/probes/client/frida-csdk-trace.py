#!/usr/bin/env python3
"""Stay attached: trace ClientSDK anticheat fail and config lookup.

Prints a backtrace when AZCore logs a ClientSDK/anticheat string, and
whether FUN_146193620 / the enable-anticheat lookup actually run on Play.
Must stay attached (Interceptor).
"""

from __future__ import annotations

import sys
import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { throw new Error('no NewWorld.exe'); }
const base = mod.base;
const off = (va) => va.sub(ptr('0x140000000'));
const a = (va) => base.add(off(ptr(va)));

function cstr(p) {
  try { return p.readCString(); } catch (e) { return null; }
}

Interceptor.attach(a('0x1461A54F0'), {
  onEnter(args) {
    this.key = cstr(args[1]) || '';
  },
  onLeave(ret) {
    const k = this.key;
    if (k.indexOf('anticheat') >= 0 || k.indexOf('eos') >= 0 || k === 'game-security') {
      send({lookup: k, ok: ret.toInt32()});
    }
  }
});

Interceptor.attach(a('0x146193620'), {
  onEnter() { send({gamesec: 'enter'}); },
  onLeave(ret) { send({gamesec: 'leave', ret: ret.toInt32()}); }
});

Interceptor.attach(a('0x1402B6E60'), {
  onEnter(args) {
    const s = cstr(args[1]) || '';
    if (!s) return;
    const hit = s.indexOf('anticheat') >= 0 || s.indexOf('csdkerr') >= 0
      || s.indexOf('ClientSDK') >= 0 || s.indexOf('authorized') >= 0
      || s.indexOf('eos_unknown') >= 0;
    if (!hit) return;
    const bt = Thread.backtrace(this.context, Backtracer.ACCURATE)
      .slice(0, 12)
      .map(DebugSymbol.fromAddress)
      .map(String);
    send({log: s.slice(0, 180), bt: bt});
  }
});

send({ready: true, base: base.toString()});
"""


def main() -> int:
    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        print("NewWorld.exe not running")
        return 1

    def on_msg(msg, _data):
        payload = msg.get("payload") if msg.get("type") == "send" else msg
        print(payload, flush=True)

    script = session.create_script(JS)
    script.on("message", on_msg)
    script.load()
    print("[azoth] csdk-trace attached; waiting for Jugar", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
