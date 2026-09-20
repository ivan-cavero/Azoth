#!/usr/bin/env python3
"""Force GameConnection past WaitingForActorGameConnection (Frida).

After V3 the client sits in state 0xB until carrier[+0xA0]==2
(FUN_145a92370). CLOCK_SYNC keepalives stop the 10s ClientSDK
disconnect but the 2 min connection_game_timeout still fires
(Game.log 2026-09-18 20:23:49). These three getters are the
11→12→13 ladder:

    0x145A92370  [carrier+0xA0]==2     actor game connection
    0x145A905C0  [carrier+0xBC8]       spawn point found
    0x145A923C0  [carrier+0x252]       player spawn

Byte-patch each to `mov al,1; ret`. Patches persist after detach.
"""

from __future__ import annotations

import time

import frida

IMAGE_BASE = 0x140000000
PATCHES = (
    # Live 1.400 uses disp32 `83 B9 A0 00 00 00 02`, not disp8 `83 79 A0`.
    (0x145A92370, bytes.fromhex("83 B9 A0"), bytes.fromhex("B0 01 C3")),
    (0x145A905C0, bytes.fromhex("0F B6 81"), bytes.fromhex("B0 01 C3")),
    (0x145A923C0, bytes.fromhex("0F B6 81"), bytes.fromhex("B0 01 C3")),
)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ok: false, err: 'no-module'}); } else {
  const base = mod.base;
  const patches = %PATCHES%;
  const report = [];
  for (const p of patches) {
    const addr = base.add(p.va - 0x140000000);
    const n = p.want.length;
    const before = new Uint8Array(addr.readByteArray(n));
    const orig = new Uint8Array(p.orig);
    let match = true;
    for (let i = 0; i < orig.length; i++) if (before[i] !== orig[i]) match = false;
    let already = true;
    for (let i = 0; i < n; i++) if (before[i] !== p.want[i]) already = false;
    if (!match && !already) {
      report.push({va: p.va.toString(16), err: 'mismatch', before: Array.from(before)});
      continue;
    }
    Memory.patchCode(addr, n, function (code) {
      for (let i = 0; i < n; i++) code.add(i).writeU8(p.want[i]);
    });
    report.push({va: p.va.toString(16), ok: true, before: Array.from(before)});
  }
  send({ok: true, base: base.toString(16), report: report});
}
"""


def main() -> int:
    patches_js = "[" + ",".join(
        "{va:%d,orig:[%s],want:[%s]}"
        % (
            va,
            ",".join(str(b) for b in orig),
            ",".join(str(b) for b in want),
        )
        for va, orig, want in PATCHES
    ) + "]"
    js = JS.replace("%PATCHES%", patches_js)
    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        print("NewWorld.exe not running")
        return 1
    result: list = []
    script = session.create_script(js)
    script.on("message", lambda m, _d: result.append(m.get("payload") or m))
    script.load()
    for _ in range(20):
        if result:
            break
        time.sleep(0.1)
    print(result)
    session.detach()
    ok = bool(result) and isinstance(result[0], dict) and result[0].get("ok")
    print("[azoth] ladder force", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
