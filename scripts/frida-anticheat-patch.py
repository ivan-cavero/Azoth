#!/usr/bin/env python3
"""Patch the ClientSDK anticheat gate (Frida, OUR runtime).

The client disconnects with `Errors::connection_server_requires_anticheat`
immediately after the V3 handshake. Interceptor.attach/replace on these
sites did NOT fire (2026-09-18 live: error still 6ms after socket up
with the hooks loaded). Byte-patch like frida-trust-patch.py: the
patched opcodes persist after detach.

Sites (build 1.400.6031.6004151):

    FUN_145a8ddd0  vtable+0x90 impl: OmniSDK status then [obj+0x25c]
                   -> `mov al,1; ret`  (B0 01 C3)
    FUN_145a8de00  thunk: if [obj+0x228] jmp [vtable+0x90] else al=1
                   -> `mov al,1; ret`
    FUN_1479b61e0  OmniSDK session status (returns 100 when EOS is down)
                   -> `xor eax,eax; ret`  (31 C0 C3)

Usage:
  python scripts/frida-anticheat-patch.py            # attach, patch, detach
  python scripts/frida-anticheat-patch.py --stay     # keep the session open
"""

from __future__ import annotations

import argparse
import time

import frida

IMAGE_BASE = 0x140000000
PATCHES = (
    # (VA, original bytes as sanity, patched bytes)
    (0x145A8DDD0, bytes.fromhex("40 53 48"), bytes.fromhex("B0 01 C3")),
    (0x145A8DE00, bytes.fromhex("48 8B 89"), bytes.fromhex("B0 01 C3")),
    (0x1479B61E0, bytes.fromhex("48 89 5C"), bytes.fromhex("31 C0 C3")),
    # FUN_146193620: six `sete [rbp+0x6f]` after `cmp ecx, 0x102`.
    # Each stores 1 whenever the JSON value is a bool (type 0x102),
    # including JSON `false`. Force every stored byte to 0.
    (0x1461936E3, bytes.fromhex("0F 94 45 6F"), bytes.fromhex("C6 45 6F 00")),
    (0x1461937C4, bytes.fromhex("0F 94 45 6F"), bytes.fromhex("C6 45 6F 00")),
    (0x146193988, bytes.fromhex("0F 94 45 6F"), bytes.fromhex("C6 45 6F 00")),
    (0x146193B45, bytes.fromhex("0F 94 45 6F"), bytes.fromhex("C6 45 6F 00")),
    (0x14619401F, bytes.fromhex("0F 94 45 6F"), bytes.fromhex("C6 45 6F 00")),
    (0x1461940FC, bytes.fromhex("0F 94 45 6F"), bytes.fromhex("C6 45 6F 00")),
    # FUN_1444f5700: official skip is `this[0x130]=1; ret` when the
    # global+0x244/245/246 flags are set. That path means "EOS is not
    # running". Combined with enable-anticheat stored 0, ClientSDK
    # must not demand an anticheat session. Without the S3/store fix
    # this is the SAME encoding as the resolve-fail path and still
    # raises @mm_csdkerr_server_requires_anticheat.
    (0x1444F5700, bytes.fromhex("48 89 5C 24 08"), bytes.fromhex("C6 81 30 01 00 00 01 B0 01 C3")),
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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stay", action="store_true", help="keep attached (not required for byte patches)")
    args = ap.parse_args()

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

    result: list[dict] = []

    def on_msg(msg, _data):
        if msg.get("type") == "send":
            result.append(msg.get("payload") or {})
        else:
            print(f"[frida:{msg.get('type')}] {msg.get('description') or msg}")

    script = session.create_script(js)
    script.on("message", on_msg)
    script.load()
    for _ in range(10):
        if result:
            break
        time.sleep(0.2)
    if not result or not result[0].get("ok"):
        print("patch failed:", result)
        session.detach()
        return 1
    print("[azoth] anticheat byte-patch applied", result[0])
    if args.stay:
        print("[azoth] staying attached (Ctrl+C)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    session.detach()
    print("[azoth] detached; patches persist until the process exits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
