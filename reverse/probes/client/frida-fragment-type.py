#!/usr/bin/env python3
"""Log the 16-byte AZ type id the client resolves for each state-bundle fragment.

WHY. The capture's 79 state bundles all carry key=1 and what the current parse
calls `type_index`=1, which is suspiciously constant. If the client resolves a
fragment to a real component/message type, `FUN_1461acfe0` writes that 16-byte
type id into its second argument, and reading it settles what the server is
actually telling the client to build. That is the missing piece for the
fragment codec work (physics, NPCs).

Read-only.

Usage: python az.py probe frida-fragment-type [--timeout 120]
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const off = (va) => base.add(va - 0x140000000);
  let n = 0;
  // FUN_1461acfe0(out_bool, out_typeid, reader): resolves a fragment type index.
  Interceptor.attach(off(0x1461acfe0), {
    onEnter(args) { this.out = args[1]; },
    onLeave(ret) {
      n++;
      if (n > 60) return;
      let hex = null;
      try {
        const b = new Uint8Array(this.out.readByteArray(16));
        hex = Array.from(b).map(x => x.toString(16).padStart(2,'0')).join('');
      } catch (e) { hex = 'read-fail:' + e; }
      send({ev:'typeid', n: n, typeid: hex});
    }
  });
  setInterval(function(){ send({ev:'alive', n: n}); }, 5000);
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", default="fragment-type.jsonl")
    args = parser.parse_args()
    out_path = probe_capture(args.out)
    device = frida.get_local_device()
    session = None
    for _ in range(60):
        try:
            session = device.attach("NewWorld.exe")
            break
        except Exception:
            time.sleep(2)
    if session is None:
        raise SystemExit("could not attach")
    script = session.create_script(JS)
    handle = out_path.open("w", encoding="utf-8")

    def on_message(message, _data):
        payload = message.get("payload") if message.get("type") == "send" else message
        handle.write(json.dumps(payload) + "\n")
        handle.flush()

    script.on("message", on_message)
    script.load()
    print(f"attached; logging to {out_path}")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(5)
    try:
        session.detach()
    except Exception:
        pass
    handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
