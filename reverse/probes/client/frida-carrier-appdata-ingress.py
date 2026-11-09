#!/usr/bin/env python3
"""F4c: does the client *receive* our post-registration traffic at all?

The L9 boundary said the ladder never reaches the Carrier deframer against
Rust, while it runs thousands of times against the Python lab. That leaves two
possibilities and this probe separates them:

  * the client DISCARDS our post-registration datagrams (envelope/seq/state);
  * the client never DELIVERS them to the connection's record stream.

`FUN_146af3310` is the app-data ingress: it takes the decoded datagram, builds
the record buffer and hands it to the deframer `FUN_146ae5a70`. It has no E8
caller anywhere in .text, so it is reached through a transport vtable, which is
exactly why L9's deframer hook alone could not see the difference.

The header below is byte-checked against the private executable on disk before
the script is allowed to load: a build whose ingress has moved stops the probe
instead of hooking a neighbour's mid-instruction. (Both `30fe6461` and the
patched `97f17df3` private copy carry this header at this VA.)

Read-only. Run it against Rust and against the Python lab and compare the
`ingress` counter: Rust showing 0 ingress means the client is dropping the
datagrams before they are ever records.

Usage:  python reverse/probes/client/frida-carrier-appdata-ingress.py --timeout 600
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import frida

INGRESS = 0x146AF3310  # app-data ingress -> FUN_146b10400 -> deframer
DEFRAMER = 0x146AE5A70  # record de-frame/reassembly state machine
PARSE = 0x146B701B0

# What MUST be at those VAs before the probe attaches. Read from the private
# executable on disk, so a stale VA refuses instead of landing mid-instruction
# (the failure that killed the client three times while chasing these records).
HEADERS = {
    INGRESS: bytes.fromhex("48895c241048896c2418488974242057"),
    DEFRAMER: bytes.fromhex("48895c241048896c24185657415441 56".replace(" ", "")),
    PARSE: bytes.fromhex("48895c2410488974241848897c242055"),
}

REPO = Path(__file__).resolve().parents[3]
PRIVATE_EXE = REPO / "private-client" / "runtime" / "Bin64" / "NewWorld.exe"


def pe_bytes(va: int, n: int) -> bytes:
    """Bytes of a VA in the private exe, via the build_sites helpers."""
    import sys
    sys.path.insert(0, str(REPO / "services" / "launcher" / "runtime-tools"))
    import build_sites  # noqa: E402  (only used for read_va)
    return build_sites.read_va(PRIVATE_EXE, va, n)


def headers_ok() -> tuple[bool, list[str]]:
    """Every hook target's first bytes, verified against the executable."""
    bad = []
    for va, want in HEADERS.items():
        try:
            got = pe_bytes(va, len(want))
        except Exception as exc:
            bad.append(f"{va:#x}: unreadable ({exc})")
            continue
        if got != want:
            bad.append(f"{va:#x}: got {got.hex()} want {want.hex()}")
    return (not bad, bad)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) { send({ ev: 'error', error: 'no exe' }); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let ingress = 0, deframe = 0, parse = 0;
  const states = {};
  const firstIngress = [];
  Interceptor.attach(rva(0x146AF3310), {
    onEnter(args) {
      ingress++;
      if (firstIngress.length < 12) {
        let desc = '';
        try {
          // param_2 is the decoded payload pointer; param_3 is an
          // undefined8 that behaves as its length (READ the qword, do not
          // take() it). Both are passed to the deframer unchanged.
          const p = args[1];
          const n = Number(args[2]);
          desc = 'len=' + n + ' ptr=' + p;
          if (n > 0 && n < 512) {
            desc += ' bytes=' + hexdump(p, {length: n, ansi: false}).replace(/\n/g, ' ');
          }
        } catch (e) { desc = 'err ' + e; }
        firstIngress.push(desc);
      }
    }
  });
  Interceptor.attach(rva(0x146AE5A70), {
    onEnter() {
      deframe++;
      try { const st = this.context.rcx.readS32(); states[st] = (states[st] || 0) + 1; } catch (e) {}
    }
  });
  Interceptor.attach(rva(0x146B701B0), { onEnter() { parse++; } });
  rpc.exports = {
    status() { return { ingress: ingress, deframe: deframe, states: states, parse: parse, first: firstIngress }; }
  };
  send({ ev: 'ready', base: base.toString(16) });
}
"""


def find_game_pid():
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
    ok, bad = headers_ok()
    if not ok:
        print("[ingress] REFUSING: hook headers do not match the private executable")
        for line in bad:
            print(f"[ingress]   {line}")
        return 2
    print(f"[ingress] headers verified on {PRIVATE_EXE.name} shasum {hashlib.sha256(PRIVATE_EXE.read_bytes()).hexdigest()[:12]}", flush=True)
    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[ingress] no NewWorld.exe")
        return 1
    session = frida.attach(pid)
    script = session.create_script(JS)
    out = REPO / "sessions" / f"carrier-ingress-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n"); fh.flush()
            print(f"[ingress] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[ingress] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[ingress] live -> {out}", flush=True)
    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
                print(
                    f"[ingress] ingress={st['ingress']} deframe={st['deframe']} "
                    f"states={json.dumps(st['states'])} parse={st['parse']}",
                    flush=True,
                )
                for line in st["first"]:
                    print(f"[ingress]   {line}", flush=True)
                st["first"][:] = []
            except Exception as exc:
                print("[ingress] status error:", exc, flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
