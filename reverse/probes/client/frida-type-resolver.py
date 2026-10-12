#!/usr/bin/env python3
"""Log every type id the client's typed dispatcher resolves, with counts.

WHY. The server sends `ReceivePlayerPositionClientMsg` (wire type 4216, GUID
`39CA8BCA-2EE8-4104-B0E9-7C2A51B52FB4`, 36-byte body) and `Game.log` shows no
unmarshal or validation error — but the repo has already measured that an unused
or unknown type is dropped **silently**, so "no error" proves nothing. A live probe
on the reader's own codec (`frida-position-consumer`) counted **0** calls to
`FUN_143f98750` / `FUN_143f97d10` while the server logged dozens of `position-reply`
events on both channel 1 (unreliable) and channel 0 (reliable).

So the question is now precise: **does the client resolve type 4216 at all?**

`FUN_1461acfe0(out_bool, out_typeid, reader)` is the type resolver the client uses
on the typed stream. Hooking it and reading the 16-byte GUID it writes answers the
question directly and also lists, by count, exactly which message types the client
is consuming in a session — the same instrument that produced the
"0x15d / 0x1096 / 0x1097" finding in `STATUS.md`.

Interpretation:
  * 4216 appears -> the message is dispatched; the failure is downstream (the
    handler ignores it or the local player has no position receiver).
  * 4216 never appears -> the record never reaches the typed path. Then the
    container, channel, or flags are wrong, and the next step is the framing.

Read-only. Private no-EAC client.

Usage:
  python az.py probe frida-type-resolver --timeout 900
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

RESOLVER = 0x1461ACFE0

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const counts = {};
  let n = 0;

  Interceptor.attach(rva(0x1461acfe0), {
    onEnter(args) { this.out = args[1]; },
    onLeave(retval) {
      n++;
      let hex = null;
      try {
        const b = new Uint8Array(this.out.readByteArray(16));
        hex = Array.from(b).map(x => x.toString(16).padStart(2, '0')).join('');
      } catch (e) {
        hex = 'read-fail';
      }
      counts[hex] = (counts[hex] || 0) + 1;
      if (counts[hex] === 1) send({ ev: 'new-type', hex: hex, n: n });
    }
  });

  rpc.exports = {
    status() { return { n: n, counts: counts }; }
  };

  send({ ev: 'ready', base: base.toString(16) });
}
"""


def find_game_pid() -> int | None:
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == "newworld.exe":
            return proc.pid
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--poll", type=float, default=30.0)
    args = ap.parse_args()

    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[types] no NewWorld.exe")
        return 1

    # Map typeIndex GUID -> index once, so the report names types.
    index: dict[str, int] = {}
    ti = Path(__file__).resolve().parents[2] / "private-client" / "runtime" / "typeindex.json"
    if ti.is_file():
        data = json.loads(ti.read_text(encoding="utf-8"))
        for i, g in enumerate(data.get("typeIndex", [])):
            if g:
                index[g.lower()] = i

    session = frida.attach(pid)
    script = session.create_script(JS)

    out = Path(__file__).resolve().parents[2] / "sessions" / f"type-resolver-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def name_of(hex16: str) -> str:
        # The resolver writes the GUID in mixed-endian "GUID" layout; try both.
        g = hex16.lower()
        swapped = (g[6:8] + g[4:6] + g[2:4] + g[0:2] + g[10:12] + g[8:10]
                   + g[14:16] + g[12:14] + g[16:])
        for cand in (g, swapped):
            if cand in index:
                return f"index {index[cand]}"
        return "?"

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            if payload.get("ev") == "new-type":
                payload["name"] = name_of(payload["hex"])
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[types] {json.dumps(payload)[:200]}", flush=True)
        else:
            print("[types] err:", str(m.get("description"))[:200], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[types] live -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
            except Exception as exc:  # noqa: BLE001
                print("[types] status error:", exc, flush=True)
                continue
            named = {name_of(k): v for k, v in st["counts"].items()}
            print(f"[types] n={st['n']} {json.dumps(named)}", flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
