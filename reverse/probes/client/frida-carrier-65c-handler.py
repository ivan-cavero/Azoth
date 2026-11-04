#!/usr/bin/env python3
"""Does our server's `0x65c` self-ident reach its client handler? (dispatch vs guard)

CONTEXT. The rung-15 gate is: handler `FUN_146455ec0` (wire `0x65c`,
PlayerManagerSelfIdentificationMsg) -> `FUN_145a88140` -> `[carrier+0xA0] = 2`, gated by
`(GUID at param_5 == local player GUID) || (*FUN_14100a1f0() == 0) || (param_6[10] != 0)`.
Against the PYTHON world the store fires and the client crosses; against OUR Rust server
the flag stays 1 and the store never fires. This probe answers the fork:

  * `call-65c` appears  -> the `0x65c` DID reach the handler; the guard is what fails.
  * `call-65c` missing  -> the `0x65c` never reaches the handler (dispatch/framing/order).

It also logs, per `0x65c` call, `param_5` (+4..+0x14, the compared GUID) and `param_6` (+10
byte), plus the return address (the dispatcher), and counts the `0x663` handler
(`0x146447ac0`) and the setter as controls.

Usage:
  python ef.py probe frida-carrier-65c-handler --timeout 600
  (run against the PYTHON world first, then the Rust server; compare call counts)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

H_65C = 0x146455EC0
SETTER = 0x145A88140
H_663 = 0x146447AC0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let c65c = 0, cset = 0, c663 = 0;
  const sent = {};

  function hex(buf, n) {
    try {
      const b = new Uint8Array(buf);
      return Array.from(b.slice(0, n)).map((x) => x.toString(16).padStart(2, '0')).join('');
    } catch (e) { return null; }
  }
  function once(key, payload) {
    sent[key] = (sent[key] || 0) + 1;
    if (sent[key] <= 4) send(payload);
  }

  Interceptor.attach(rva(0x146455EC0), {
    onEnter() {
      c65c++;
      let p5 = null, p6 = null, ret = null, g = null, b10 = null;
      try {
        const rsp = this.context.rsp;
        p5 = rsp.add(0x28).readPointer();   // param_5 (5th arg)
        p6 = rsp.add(0x30).readPointer();   // param_6 (6th arg)
        ret = this.returnAddress;
        if (!p5.isNull()) { g = hex(Memory.readByteArray(p5.add(4), 16), 16); }
        if (!p6.isNull()) { try { b10 = p6.add(10).readU8(); } catch (e) {} }
      } catch (e) {}
      once('65c', { ev: 'call-65c', n: c65c, param5: p5 && p5.toString(),
                    guid_at_p5p4: g, param6: p6 && p6.toString(), param6_b10: b10,
                    ret_rva: ret ? ret.sub(base).toString(16) : null });
    }
  });

  Interceptor.attach(rva(0x145A88140), {
    onEnter() { cset++; once('set', { ev: 'call-setter', n: cset }); }
  });

  Interceptor.attach(rva(0x146447AC0), {
    onEnter() { c663++; once('663', { ev: 'call-663', n: c663 }); }
  });

  rpc.exports = { status() { return { c65c: c65c, cset: cset, c663: c663 }; } };
  send({ ev: 'ready', base: base.toString(16) });
}
"""


def find_game_pid() -> int | None:
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == "newworld.exe":
            return proc.pid
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--poll", type=float, default=15.0)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[h65c] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS)

    out = Path(__file__).resolve().parents[3] / "sessions" / f"carrier-65c-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[h65c] {json.dumps(payload)[:400]}", flush=True)
        else:
            print("[h65c] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[h65c] live -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(f"[h65c] counts 65c={st['c65c']} setter={st['cset']} 663={st['c663']}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("[h65c] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
