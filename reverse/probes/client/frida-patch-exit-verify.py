#!/usr/bin/env python3
"""Apply the 20-minute-exit patch to a RUNNING private client and verify it.

`frida-patch-exit-once` reported `access violation accessing <site>` on
2026-10-11 and the patch never landed, so the "does the session survive the
20-minute delegate?" question is still open. This version is deliberately
defensive:

  * it resolves the site from the live module base and prints the base, the site
    and the containing memory range's protection BEFORE it touches anything;
  * it uses `Memory.patchCode` (which re-protects the page, writes, and restores)
    instead of a manual `Memory.protect` + `writeByteArray`;
  * it reads the five bytes back and reports `ok: true/false`.

The patch NOPs the `call CGame::ActorContainerDisconnect` at VA 0x141004230
(`e8 db c3 41 05`), the single 5-byte call that tears the world down when the
queued 20-minute delegate fires.

Usage:
  python reverse/probes/client/frida-patch-exit-verify.py
  python reverse/probes/client/frida-patch-exit-verify.py --restore
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
  const hex = (p, n) => Array.from(new Uint8Array(p.readByteArray(n)))
                            .map(b => b.toString(16).padStart(2, '0')).join('');
  let range = null;
  try {
    const r = Process.findRangeByAddress(site);
    if (r !== null) range = { base: r.base.toString(), size: r.size, protection: r.protection };
  } catch (e) {}
  const before = hex(site, 5);
  let ok = false, err = null, after = null;
  try {
    Memory.patchCode(site, 5, (code) => { code.writeByteArray(%BYTES%); });
    after = hex(site, 5);
    ok = (after === %EXPECT%);
  } catch (e) {
    err = String(e);
    try { after = hex(site, 5); } catch (e2) { after = 'read-fail'; }
  }
  send({ ev: 'done', base: base.toString(), site: site.toString(), range: range,
         before: before, after: after, ok: ok, error: err });
}
"""

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    want = ORIGINAL if args.restore else NOP5
    bytes_literal = "[" + ", ".join(f"0x{b:02x}" for b in want) + "]"
    expect = '"' + "".join(f"{b:02x}" for b in want) + '"'

    session = frida.attach("NewWorld.exe")
    script = session.create_script(
        JS.replace("%BYTES%", bytes_literal).replace("%EXPECT%", expect)
    )
    script.on("message", lambda m, d: print("[patch-exit]", m.get("payload", m), flush=True))
    script.load()
    time.sleep(1)
    session.detach()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
