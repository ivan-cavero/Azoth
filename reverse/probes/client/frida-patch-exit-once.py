#!/usr/bin/env python3
"""Apply the 20-minute-exit patch to a RUNNING private client, once.

`frida-exit-patch` needs the patch in place before the delegate fires and also
wants to observe; when a session is already up and a long-lived probe is already
attached, this one-shot applies just the write so the two concerns stay separate.

What it writes: five `int3`-free NOPs over the `call CGame::ActorContainerDisconnect`
at VA 0x141004230 (RVA 0x1004230). `.text` is mapped `r-x`, so the page is
re-protected for the write and set back afterwards. Verified by reading the bytes
back and reporting both sides.

Usage:
  python reverse/probes/client/frida-patch-exit-once.py
  python reverse/probes/client/frida-patch-exit-once.py --restore
"""

from __future__ import annotations

import argparse
import time

import frida

CALL_VA = 0x141004230
NOP5 = [0x90] * 5
ORIGINAL = [0xE8, 0xDB, 0xC3, 0x41, 0x05]

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const site = base.add(0x141004230 - 0x140000000);
  const hex = (p) => Array.from(new Uint8Array(p.readByteArray(5)))
                            .map(b => b.toString(16).padStart(2, '0')).join('');
  const before = hex(site);
  Memory.protect(site, 0x1000, 'rwx');
  try {
    site.writeByteArray(%BYTES%);
  } finally {
    Memory.protect(site, 0x1000, 'r-x');
  }
  const after = hex(site);
  send({ ev: 'done', site: site.toString(), before: before, after: after });
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    bytes_literal = "[" + ", ".join(f"0x{b:02x}" for b in (ORIGINAL if args.restore else NOP5)) + "]"

    session = frida.attach("NewWorld.exe")
    script = session.create_script(JS.replace("%BYTES%", bytes_literal))
    script.on("message", lambda m, d: print("[patch-once]", m.get("payload", m), flush=True))
    script.load()
    time.sleep(1)
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
