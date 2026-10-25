#!/usr/bin/env python3
"""Does the client's typed dispatcher actually run the IPositionReceiver reader?

WHY. The server already builds and sends `ReceivePlayerPositionClientMsg`
(wire type 4216, varint `b8 41`, 36-byte body) and a live run logged zero
`Failed to unmarshal` / `ValidationError` / `transportError`. But "no error" is
weak evidence: the repo has already measured that an unknown or unused type is
dropped **silently**, so the client log cannot distinguish "parsed and applied"
from "ignored". The player does not move, so the honest question is whether the
reader runs at all.

The static chain is known (`research/docs/JAVELIN-DISPATCH.md`,
`.azoth/night/subagent-movement-codecs.md`):

    FUN_143f98750   facet slot5 wrapper (stamps the object vtable, calls the reader)
      -> FUN_143f97d10   the reader: 16 raw bytes, u64 BE, then 3x u32 BE into obj+0x30

This probe counts calls to both and, on the reader's return, dumps the fields it
just filled (`obj+0x30` 16-byte compound, `obj+0x40` u64) so the decoded values
can be compared with what the server sent. It also counts entries to the typed
dispatcher `FUN_146b6f190` as a control.

Interpretation:
  * reader runs and the values match what we sent -> the client parses and stores
    our position; the missing piece is downstream (a handler / the body gate);
  * reader never runs -> our reply is not being dispatched as a typed message,
    and the record framing or the channel is wrong. That is the more likely
    outcome given that every observed client->server record carries a 24-byte
    `[u32 tag][u32 len][16-byte target]` prefix that the server never sends.

Read-only. Private no-EAC client; Steam untouched.

Usage:
  python ef.py probe frida-position-consumer --timeout 900
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

FACET = 0x143F98750     # facet slot5 wrapper for ReceivePlayerPositionClientMsg
READER = 0x143F97D10    # the reader that fills obj+0x30 / obj+0x40
DISPATCH = 0x146B6F190  # typed inbound dispatcher (control counter)

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let facetCalls = 0;
  let readerCalls = 0;
  let dispCalls = 0;
  const samples = [];

  Interceptor.attach(rva(0x143f98750), {
    onEnter(args) {
      facetCalls++;
      this.obj = args[2];
      if (facetCalls <= 5) send({ ev: 'facet-enter', n: facetCalls });
    },
    onLeave(retval) {
      if (facetCalls <= 5) send({ ev: 'facet-leave', n: facetCalls, ret: retval.toString() });
    }
  });

  Interceptor.attach(rva(0x143f97d10), {
    onEnter(args) {
      readerCalls++;
      this.obj = args[0];
      this.stream = args[1];
    },
    onLeave(retval) {
      const o = this.obj;
      let pos = null, id = null;
      try {
        pos = [
          o.add(0x30).readU32().toString(16),
          o.add(0x34).readU32().toString(16),
          o.add(0x38).readU32().toString(16),
          o.add(0x3c).readU32().toString(16),
        ].join(' ');
        id = o.add(0x40).readU64().toString(16);
      } catch (e) {}
      if (readerCalls <= 10) {
        send({ ev: 'reader', n: readerCalls, pos: pos, id: id });
      } else if (readerCalls % 200 === 0) {
        send({ ev: 'reader', n: readerCalls, pos: pos, id: id });
      }
    }
  });

  Interceptor.attach(rva(0x146b6f190), {
    onEnter() { dispCalls++; }
  });

  rpc.exports = {
    status() {
      return { facet: facetCalls, reader: readerCalls, dispatch: dispCalls };
    }
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
        print("[pos] no NewWorld.exe")
        return 1

    session = frida.attach(pid)
    script = session.create_script(JS)

    out = Path(__file__).resolve().parents[2] / "sessions" / f"pos-consumer-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", encoding="utf-8")

    def on_message(m, _d):
        if m.get("type") == "send":
            payload = m["payload"]
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            print(f"[pos] {json.dumps(payload)[:300]}", flush=True)
        else:
            print("[pos] err:", str(m.get("description"))[:300], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[pos] live -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(args.poll)
            try:
                st = script.exports_sync.status()
            except Exception as exc:  # noqa: BLE001
                print("[pos] status error:", exc, flush=True)
                continue
            print(f"[pos] counts facet={st['facet']} reader={st['reader']} dispatch={st['dispatch']}",
                  flush=True)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
