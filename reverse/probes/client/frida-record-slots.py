#!/usr/bin/env python3
"""Report, per state-bundle record, whether the client CREATES or UPDATES it.

WHY. The client's record dispatcher `FUN_141717fc0` has two structurally different apply
paths, and which one runs is decided by ONE thing: whether the handler slot
`state + 0x608 + record_id*0x10` was EMPTY when the record arrived.

    slot EMPTY   -> CREATION: it builds the entity and applies the whole record in one call
    slot PRESENT -> UPDATE: it walks the fragments and applies them one by one

That distinction is the whole question for creating an entity, and it cannot be answered from
the server side: the server can send a record under a free id and log it, but only the client
can say whether that id was actually free in ITS table. This probe reads the slot on entry,
before the call, so it sees the state the dispatcher itself is about to branch on.

Reported per record: the record id, the fragment count, whether the slot was empty, and the
slot's value after the call. A record id that appears with `slotEmpty: true` once and then
`false` afterwards is an entity the client built on the first message and is now updating.

Read-only. Ends through `_paths.safe_shutdown()`; `device.kill` is the default because this
hooks a per-record function.

Usage: python ef.py probe frida-record-slots [--timeout 240]
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture, safe_shutdown

DISPATCHER = 0x141717FC0
SLOT_BASE = 0x608
SLOT_STRIDE = 0x10

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { send({ev:'error', msg:'no NewWorld.exe'}); } else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);

  const seen = {};

  Interceptor.attach(rva(%DISPATCHER%), {
    onEnter(args) {
      // args: state, record_id, &fragment_vector, msg_seq, byte[msg+8], reader_ok, ctxInstanceId
      this.state = args[0];
      const rid = args[1].toInt32() & 0xffff;
      this.rid = rid;
      this.flag = args[4].toInt32() & 0xff;
      // THE DECISIVE READ: the slot the dispatcher is about to branch on.
      let slot = null;
      let slotEmpty = null;
      try {
        slot = this.state.add(%SLOT_BASE% + rid * %SLOT_STRIDE%).readPointer();
        slotEmpty = slot.isNull();
      } catch (e) { /* reported as null */ }
      this.slot = slot;
      this.slotEmpty = slotEmpty;
      // THE WHOLE SLOT TABLE, dumped once. This is the only reliable way to know which
      // record ids are GENUINELY free: the capture-derived set is a LOWER BOUND (it was
      // built from the FIRST record of each payload, and a payload is a SEQUENCE of
      // records), so picking an id from it is how the first attempt chose a slot that was
      // already in use and turned a creation into a silently-dropped update.
      if (!this.dumped) {
        this.dumped = true;
        const table = [];
        for (let rid = 0; rid < 256; rid++) {
          try {
            const v = this.state.add(%SLOT_BASE% + rid * %SLOT_STRIDE%).readPointer();
            if (!v.isNull()) table.push(rid);
          } catch (e) {}
        }
        send({ ev: 'slot-table', used: table });
      }
    },
    onLeave(ret) {
      const key = String(this.rid);
      seen[key] = (seen[key] || 0) + 1;
      const first = seen[key] === 1;
      let slotAfter = null;
      try { slotAfter = this.state.add(%SLOT_BASE% + this.rid * %SLOT_STRIDE%).readPointer().toString(); }
      catch (e) {}
      send({
        ev: 'record', recordId: this.rid, fragments: this.frags,
        slotEmpty: this.slotEmpty, slot: this.slot ? this.slot.toString() : null,
        slotAfter: slotAfter, flag: this.flag, n: seen[key], first: first,
      });
    }
  });

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
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--wait", type=int, default=60)
    ap.add_argument("--record", type=int, default=None,
                    help="only print this record id (still records all)")
    args = ap.parse_args()

    device = frida.get_local_device()
    pid = find_game_pid()
    deadline = time.time() + args.wait
    while pid is None and time.time() < deadline:
        time.sleep(2)
        pid = find_game_pid()
    if pid is None:
        print("[slots] no NewWorld.exe")
        return 1

    session = device.attach(pid)
    source = (JS.replace("%DISPATCHER%", hex(DISPATCHER))
                .replace("%SLOT_BASE%", hex(SLOT_BASE))
                .replace("%SLOT_STRIDE%", hex(SLOT_STRIDE)))
    script = session.create_script(source)

    out = probe_capture(f"record-slots-{int(time.time())}.jsonl")
    fh = out.open("a", encoding="utf-8")
    creations: dict[int, dict] = {}

    def on_message(m, _d):
        if m.get("type") != "send":
            print("[slots] err:", str(m.get("description"))[:200], flush=True)
            return
        payload = m["payload"]
        fh.write(json.dumps(payload) + "\n")
        fh.flush()
        if payload.get("ev") != "record":
            print(f"[slots] {json.dumps(payload)[:200]}", flush=True)
            return
        rid = payload["recordId"]
        # A creation is the FIRST time a record id is seen with an empty slot.
        if payload.get("slotEmpty") and rid not in creations:
            creations[rid] = payload
            print(f"[slots] CREATION record_id={rid} fragments={payload['fragments']} "
                  f"flag={payload['flag']} slotAfter={payload['slotAfter']}", flush=True)
        elif args.record is not None and rid == args.record:
            print(f"[slots] record_id={rid} n={payload['n']} fragments={payload['fragments']} "
                  f"slotEmpty={payload['slotEmpty']}", flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[slots] live pid={pid} -> {out}", flush=True)

    end = time.time() + args.timeout
    try:
        while time.time() < end:
            time.sleep(20)
            print(f"[slots] creations so far: {sorted(creations)}", flush=True)
    except KeyboardInterrupt:
        pass

    print(f"[slots] final creations: {sorted(creations)}", flush=True)
    for rid, payload in sorted(creations.items()):
        print(f"[slots]   {rid}: fragments={payload['fragments']} flag={payload['flag']}",
              flush=True)
    fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
