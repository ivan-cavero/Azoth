#!/usr/bin/env python3
"""Force the 4th spawn gate (13->14) by NOPing the FSM call-site check.

Two chained gates in the FSM block at 0x14644a8bd:

    14644a8c4  call 0x145a923c0        ; [carrier+0x252] (already forced 1)
    14644a8c9  test al, al
    14644a8cb  je 0x14644a9ac
    14644a8d1  call 0x141026080        ; singleton manager
    14644a8df  call qword ptr [rdx+0x30]  ; virtual -> 0x146800d10
    14644a8ed  test rax, rax           <-- 2 bytes: 48 85 C0
    14644a8f0  je 0x14644a9ac          ; stuck here: returns [mgr+8] == NULL

The virtual returns [mgr+8] (local player entity, created by the replica
stream the client never processed). NOPing `test rax,rax` at 0x14644a8ed
makes the `je` fall through: the FSM transitions 13->14 regardless. The
getter body stays intact (600+ other callers keep correct behavior) —
patching the function body itself crashed the client (c0000005 @
NewWorld+0x104285d, WER 2026-09-19 20:01/20:11).

Frida, our private runtime only (no EAC process; EAC.md scope).
"""

from __future__ import annotations

import time

import frida

SITE = 0x14644A8ED  # test rax, rax (after the manager virtual call)
ORIG = bytes.fromhex("4885C0")  # test rax, rax
WANT = bytes.fromhex("909090")  # nop x3

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
const base = mod.base;
const addr = base.add(%SITE% - 0x140000000);
const orig = %ORIG%;
const want = %WANT%;
const before = new Uint8Array(addr.readByteArray(orig.length));
let match = true, already = true;
for (let i = 0; i < orig.length; i++) {
  if (before[i] !== orig[i]) match = false;
  if (before[i] !== want[i]) already = false;
}
if (!match && !already) {
  send({ok: false, err: 'mismatch', before: Array.from(before)});
} else {
  Memory.patchCode(addr, want.length, function (code) {
    for (let i = 0; i < want.length; i++) code.add(i).writeU8(want[i]);
  });
  send({ok: true, before: Array.from(before)});
}
"""


def main() -> int:
    js = (
        JS.replace("%SITE%", hex(SITE))
        .replace("%ORIG%", "[" + ",".join(map(str, ORIG)) + "]")
        .replace("%WANT%", "[" + ",".join(map(str, WANT)) + "]")
    )
    session = frida.attach("NewWorld.exe")
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
    print("[azoth] spawn-gate NOP", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
