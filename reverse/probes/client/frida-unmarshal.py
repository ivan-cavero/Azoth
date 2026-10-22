#!/usr/bin/env python3
"""Log what the client's UNMARSHAL actually reads, per typed message.

WHY THIS EXISTS. `research/atlas/presence-codecs.json` identifies the six message types a
server needs to replicate actors (449 AddActorMessage, 574 SpawnActorsMsg, 391 Replicate,
407 ReplicateClient, 422 FragmentUpdateMsg, 106 UpdateMsg), but records that their WIRE
LAYOUTS are unknown, because the static route that decoded the movement family on build
1.400 does not reach 1.460: the name and GUID strings have zero rip-relative referrers, the
16-byte GUID forms occur zero times, and FUN_1407de270 has no callers. The descriptor tables
are assembled at runtime.

So the layouts have to be observed. This probe hooks the unmarshal that logs
"Failed to unmarshal" on THIS build and records, for every message that reaches it, the
type index and the payload bytes the client hands to its reader. Sending a message with a
known payload and reading what arrived is how the layout gets established.

THE HOOK, and how it was found for build 1.460 (30fe6461, image base 0x140000000):
  * the string "Failed to unmarshal" lives at VA 0x1484d7480;
  * it has ZERO rip-relative referrers, so it cannot be found by xref walking;
  * a whole-corpus search for that VA lands in exactly ONE function:
    **FUN_1461adb90** (range 0x1461adb90-0x1461adf54), which passes the string to the log
    helper FUN_146147410 and hands the payload on via FUN_1417b33a0 with `param_3 + 0x18`.

This probe hooks FUN_1461adb90 and dumps its arguments. It is READ-ONLY: it logs, it does
not write memory and does not change control flow.

Usage:
  python az.py probe frida-unmarshal --timeout 600
  python az.py probe frida-unmarshal --timeout 600 --out .azoth/logs/unmarshal.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import frida

IMAGE_BASE = 0x140000000
# Build 1.460.6033.6024067 / 30fe6461...
UNMARSHAL_VA = 0x1461ADB90

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({kind: 'error', err: 'no NewWorld.exe module'}); }
else {
  const base = mod.base;
  const target = base.add(%OFFSET%);
  send({kind: 'ready', base: base.toString(), target: target.toString()});

  Interceptor.attach(target, {
    onEnter(args) {
      // FUN_1461adb90(param_1, param_2, param_3, param_4)
      // param_3 is the reader/context pointer the body advances (+0x18, +0x30, +0x6c).
      let p3 = null, p2 = null, p4 = null;
      try { p3 = args[2]; } catch (e) {}
      try { p2 = args[1]; } catch (e) {}
      try { p4 = args[3]; } catch (e) {}
      const rec = {
        kind: 'unmarshal',
        t: Date.now(),
        p1: args[0].toString(),
        p2: p2 ? p2.toString() : null,
        p3: p3 ? p3.toString() : null,
        p4: p4 ? p4.toString() : null,
      };
      // Best-effort reads. A wrong offset yields garbage, not a crash, because
      // every read is guarded and the probe must never take the client down.
      const tryU32 = (addr) => { try { return addr.readU32(); } catch (e) { return null; } };
      const tryHex = (addr, n) => {
        try { return Array.from(new Uint8Array(addr.readByteArray(n))); } catch (e) { return null; }
      };
      // param_3 is a uint* FLAGS word (`*param_3 >> 2 & 1` is tested in the body),
      // and param_3+6 (i.e. +0x18 bytes) is a second flag block. The PAYLOAD is
      // param_4, the reader object, which is why reading param_3 gave all zeroes on
      // the first run (731 calls, one shape). Read the flags properly and dump the
      // reader's head so the buffer pointers can be followed on the next iteration.
      if (p3 !== null) {
        rec.flags = tryU32(p3);
        rec.flags18 = tryU32(p3.add(0x18));
      }
      if (p4 !== null) {
        rec.p4_head = tryHex(p4, 64);
        rec.p4_0x00 = tryU32(p4);
        rec.p4_0x08 = tryU32(p4.add(8));
        rec.p4_0x10 = tryU32(p4.add(0x10));
        rec.p4_0x18 = tryU32(p4.add(0x18));
        // follow the first pointer-looking qword if it lands in a mapped range
        try {
          const q0 = p4.readPointer();
          if (q0 && !q0.isNull()) rec.p4_ptr0_head = tryHex(q0, 64);
        } catch (e) {}
        try {
          const q1 = p4.add(8).readPointer();
          if (q1 && !q1.isNull()) rec.p4_ptr1_head = tryHex(q1, 64);
        } catch (e) {}
      }
      send(rec);
    }
  });
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=600, help="seconds to stay attached")
    ap.add_argument("--out", default="", help="also append the records to this JSONL file")
    ap.add_argument("--pid", type=int, default=0, help="attach to this pid instead of finding one")
    args = ap.parse_args()

    pid = args.pid
    if not pid:
        for proc in frida.get_local_device().enumerate_processes():
            if proc.name.lower() == "newworld.exe":
                pid = proc.pid
                break
    if not pid:
        print("NewWorld.exe not running; launch the private client first", file=sys.stderr)
        return 2

    sink = open(args.out, "a", encoding="utf-8") if args.out else None
    counts: dict[str, int] = {}

    def on_message(message, data):  # noqa: ANN001
        if message.get("type") == "error":
            print(f"[probe] script error: {message.get('description')}", file=sys.stderr)
            return
        payload = message.get("payload") or {}
        kind = payload.get("kind")
        if kind in ("ready", "error"):
            print(f"[probe] {kind}: {payload}")
            return
        if kind != "unmarshal":
            return
        # Deduplicate by the shape we care about so the log stays readable.
        key = (payload.get("flags"), payload.get("p4_0x00"))
        counts[str(key)] = counts.get(str(key), 0) + 1
        line = json.dumps(payload, separators=(",", ":"))
        if sink:
            sink.write(line + "\n")
            sink.flush()
        print(f"[unmarshal] flags={payload.get('flags')} p4_0x00={payload.get('p4_0x00')} p4_0x08={payload.get('p4_0x08')}")

    session = frida.attach(pid)
    script = session.create_script(JS.replace("%OFFSET%", str(UNMARSHAL_VA - IMAGE_BASE)))
    script.on("message", on_message)
    script.load()
    print(f"[probe] attached to pid {pid}; hooking {UNMARSHAL_VA:#x} for {args.timeout}s")
    try:
        time.sleep(args.timeout)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            session.detach()
        except Exception:  # noqa: BLE001
            pass
        if sink:
            sink.close()
    print(f"[probe] done; {sum(counts.values())} unmarshal calls in {len(counts)} distinct shapes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
