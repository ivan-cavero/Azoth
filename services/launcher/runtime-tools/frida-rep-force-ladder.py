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

# Per-build getter addresses. The three sites move together — all three shifted by
# exactly +0x1130 on 1.460 — which is itself the cross-check that they belong to the
# same function family.
#
# 1.400.6031.6004151 / 8654f01d...: 0x145A92370, 0x145A905C0, 0x145A923C0
# 1.460.6033.6024067 / 30fe6461...: 0x145A934A0, 0x145A916F0, 0x145A934F0
#
# Each 1.460 address is the start of a TINY LEAF FUNCTION that returns one Carrier
# state, so `mov al,1; ret` replaces it cleanly. None of the three has a .pdata entry
# (no stack, no frame), which is normal for a leaf and is why they cannot be found by
# walking the function table. Verified 2026-10-25 on 30fe6461:
#
#   0x145A934A0  83 b9 a0 00 00 00 02   cmp dword [rcx+0xA0], 2
#                0f 94 c0                sete al
#                c3                      ret              -> return [rcx+0xA0] == 2
#   0x145A916F0  0f b6 81 c8 0b 00 00   movzx eax, byte [rcx+0xBC8] ; ret
#   0x145A934F0  0f b6 81 52 02 00 00   movzx eax, byte [rcx+0x252] ; ret
#
# TRAP, measured 2026-10-25: the first pattern is NOT unique. `cmp dword [rcx+0xA0], 2`
# also occurs at 0x145AA408C inside FUN_145AA4070, followed by `jne` rather than `sete`.
# An earlier version of this comment claimed "1 occurrence", which would let a
# re-derivation pick the wrong site. The address below is correct; the pattern is only
# a locator, and it needs the `0f 94 c0 c3` tail to be unambiguous.
SITES = {
    "8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e": (
        0x145A92370,
        0x145A905C0,
        0x145A923C0,
    ),
    "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033": (
        0x145A934A0,
        0x145A916F0,
        0x145A934F0,
    ),
}
DEFAULT_SITES = (0x145A934A0, 0x145A916F0, 0x145A934F0)

def resolve_patches():
    """Build the patch list for this build, keyed by the OFFICIAL exe's hash."""
    import hashlib
    import os
    from pathlib import Path

    install = os.environ.get("AZOTH_GAME_INSTALL") or r"C:\Program Files (x86)\Steam\steamapps\common\New World"
    official = Path(install) / "Bin64" / "NewWorld.exe"
    try:
        digest = hashlib.sha256(official.read_bytes()).hexdigest()
    except OSError:
        digest = ""
    actor, spawnpoint, playerspawn = SITES.get(digest, DEFAULT_SITES)
    print(f"[ladder] build {digest[:16] or 'unknown'}; sites {actor:#x}, {spawnpoint:#x}, {playerspawn:#x}")
    return (
        (actor, bytes.fromhex("83 B9 A0"), bytes.fromhex("B0 01 C3")),
        (spawnpoint, bytes.fromhex("0F B6 81"), bytes.fromhex("B0 01 C3")),
        (playerspawn, bytes.fromhex("0F B6 81"), bytes.fromhex("B0 01 C3")),
    )

PATCHES = resolve_patches()

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
