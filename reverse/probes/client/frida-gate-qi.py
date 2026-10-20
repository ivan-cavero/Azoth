#!/usr/bin/env python3
"""Read the two interfaces the slice-job QueryInterface accepts, and test it directly.

WHY. The Transform gate (`FUN_141763b70`) asks each slice job for `{83482F97-84DA-4FD4-BF9E-7FE34C8E091F}`
through `job->vtable[+0x20](job, guid)`, and `FUN_141582430` - the only function that registers
GameTransformComponent - is therefore never called. A live count showed the gate running 30 times, all 30
jobs sharing ONE vtable (RVA 0x7feaca8), with `register=0`.

Disassembling that vtable's `+0x20` slot (RVA 0x1445390) shows a REAL QueryInterface, not a stub:

    call 0x1407770f0 ; if (guid == [rax]) return this          // interface #1
    call 0x14144a220 ; if (guid == [rax]) return this          // interface #2
    return 0                                                    // anything else

So the null means `{83482F97-...}` matches NEITHER of the two. Both GUID getters are TLS-guarded
magic statics (`sub rsp; mov ecx,[tls_index]; ... lea rax,[rip+...]`), so their values are **not**
readable statically - the bytes at the `lea` target are uninitialised garbage until the init path runs.
That is why a static read produced nonsense.

WHAT THIS PROBE DOES, all read-only
===================================
1. Calls the two GUID getters and reads the 16 bytes each returns -> names the two interfaces.
2. Captures one slice job from the gate, then calls its `+0x20` QueryInterface three times: with
   `{83482F97-...}` (expect null), and with each of the two GUIDs (expect `this`). That is a direct
   confirmation of the comparison, not an inference from disassembly.

Usage:
  python az.py probe frida-gate-qi --wait 400 --timeout 200
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

GATE = 0x141763B70
GUID_GETTER_1 = 0x1407770F0
GUID_GETTER_2 = 0x14144A220
# The type id the gate asks for, as it appears in the descriptor bytes at UNK_147f02048.
GATE_WANTS = bytes.fromhex("83482f9784da4fd4bf9e7fe34c8e091f").hex()

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);

  const getGuid1 = new NativeFunction(rva(%G1%), 'pointer', []);
  const getGuid2 = new NativeFunction(rva(%G2%), 'pointer', []);

  function readGuid(ptr) {
    try {
      const b = new Uint8Array(ptr.readByteArray(16));
      let hex = '';
      for (let i = 0; i < 16; i++) hex += ('0' + b[i].toString(16)).slice(-2);
      return hex;
    } catch (e) { return 'error:' + e; }
  }

  let g1 = null, g2 = null;
  try { g1 = readGuid(getGuid1()); } catch (e) { g1 = 'throw:' + e; }
  try { g2 = readGuid(getGuid2()); } catch (e) { g2 = 'throw:' + e; }
  send({ ev: 'guids', guid1: g1, guid2: g2, gateWants: %WANTS% });

  // Capture one job and interrogate its QueryInterface.
  let tested = false;
  Interceptor.attach(rva(%GATE%), {
    onEnter(args) {
      if (tested) return;
      const job = args[0];
      if (job.isNull()) return;
      tested = true;
      try {
        const vt = job.readPointer();
        const qi = vt.add(0x20).readPointer();
        const qiFn = new NativeFunction(qi, 'pointer', ['pointer', 'pointer']);

        const results = {};
        function probe(label, hexGuid) {
          try {
            const buf = Memory.alloc(16);
            const bytes = [];
            for (let i = 0; i < 16; i++) bytes.push(parseInt(hexGuid.substr(i*2, 2), 16));
            buf.writeByteArray(bytes);
            const r = qiFn(job, buf);
            results[label] = r.isNull() ? 'null' : r.toString();
          } catch (e) { results[label] = 'throw:' + e; }
        }
        probe('gateWants', %WANTS%);
        if (g1 && g1.indexOf('error') < 0 && g1.indexOf('throw') < 0) probe('guid1', g1);
        if (g2 && g2.indexOf('error') < 0 && g2.indexOf('throw') < 0) probe('guid2', g2);

        send({ ev: 'qi', job: job.toString(), vtable: vt.toString(),
               qiFn: qi.toString(), results: results });
      } catch (e) {
        send({ ev: 'qi-error', error: String(e) });
      }
    }
  });

  send({ ev: 'ready', base: base.toString(16) });
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=200)
    args = ap.parse_args()

    source = (JS.replace("%G1%", hex(GUID_GETTER_1))
                .replace("%G2%", hex(GUID_GETTER_2))
                .replace("%GATE%", hex(GATE))
                .replace("%WANTS%", json.dumps(GATE_WANTS)))
    device = frida.get_local_device()

    def discover():
        return next((p.pid for p in device.enumerate_processes()
                     if p.name.lower() == "newworld.exe"), None)

    pid = discover()
    if pid is None and args.wait:
        deadline = time.time() + args.wait
        while pid is None and time.time() < deadline:
            time.sleep(1)
            pid = discover()
    if pid is None:
        print("[qi] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    script = session.create_script(source)
    out = probe_capture(f"gate-qi-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[qi] err:", str(m.get("description"))[:200], flush=True)
            return
        p = m["payload"]
        if fh and not fh.closed:
            fh.write(json.dumps(p) + "\n")
            fh.flush()
        ev = p.get("ev")
        if ev == "ready":
            print(f"[qi] attached base={p['base']}", flush=True)
        elif ev == "guids":
            print(f"[qi] interface #1 = {p['guid1']}", flush=True)
            print(f"[qi] interface #2 = {p['guid2']}", flush=True)
            print(f"[qi] gate asks for = {p['gateWants']}", flush=True)
        elif ev == "qi":
            print(f"[qi] job {p['job']} vtable={p['vtable']} qi={p['qiFn']}", flush=True)
            for k, v in p["results"].items():
                print(f"[qi]    {k:10s} -> {v}", flush=True)
        elif ev == "qi-error":
            print(f"[qi] qi-error {p['error'][:200]}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[qi] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    if fh and not fh.closed:
        fh.close()
    try:
        script.unload()
    except Exception:
        pass
    try:
        device.kill(pid)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
