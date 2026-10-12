#!/usr/bin/env python3
"""Dump the live local-player entity's component list, resolved by name.

WHY (completed Step 0 in HANDOFF.md). The claim that the local player lacks
physics components (`local_player_has_no_physics_20261004`) used a GUID list
shifted by one entry and was refuted by `local_player_components_step0_20261010`:
the live 126-component player entity contains CharacterPhysicsComponent and
GameRigidBodyComponent. This probe is the reproducible measurement; presence
does not establish that the body/controller is active or that movement works.

SAFETY -- read this before changing anything
--------------------------------------------
An earlier version of this probe froze the client and ended the run. Three defects,
all fixed here, and any edit must not reintroduce them:

1. **It called through garbage.** It hooked `FUN_141416740` (by-name component
   create) and treated `args[0]` as an entity, read `+0x10`/`+0x18`, then invoked
   the function pointer it found there. That argument is a SERVICE CONTAINER with
   maps at `+0xf8`/`+0x188`/`+0x2b8`, not an entity. Only `FUN_1413fb700` and
   `FUN_1413789c0` take a real entity as arg0.
2. **`dump()` walked the whole world.** It tracked every pointer it saw (12,898 in
   one run) and walked all of them every 30 s; Frida JS callbacks BLOCK the hooked
   thread, so the client hitched and froze. Evidence is now collected inside the
   hook and the tracked set is bounded.
3. **It targeted a window title.** `find_windows("New World")` matches any window
   with that text -- it attached to a BROWSER TAB after the game exited. The target
   is selected by process name, never by title.

Also: `--call-getters` is the only mode that invokes client code, it is opt-in, and
every call is guarded (the pointer must be readable, its vtable inside the module,
and the getter inside the module's code).

WHEN TO RUN IT. The player entity (124 components) is only visible **while the world
loads**, not once it is idle: an in-world idle run of `FUN_1413fb700` was measured at
478 calls, all for entities below 20 components. So start the probe BEFORE the
client enters the world and let it run through the load.

HOW the answer is obtained, in increasing order of risk:

* `--mode hooks` (default). Attaches to `FUN_1413fb700(entity, typeId*)` and
  `FUN_1413789c0(entity, component)`. From the arguments alone: which entity got the
  most lookups, its component count, and every type id the client ASKED FOR together
  with whether the client found it. A null return for a physics type is direct
  evidence of absence; a non-null return is evidence of presence. No client code is
  invoked.
* `--mode getters` (opt-in). Additionally resolves the FULL component list by calling
  each component's vtable slot 0, which is the type-id getter -- exactly what
  `FUN_1413fb700` calls for every component anyway. Guarded per call.

Usage:
  python az.py probe frida-player-components --wait 400 --timeout 1200
  python az.py probe frida-player-components --mode getters
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import frida

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import probe_capture  # noqa: E402

ROOT = HERE.parents[2]
REGISTRY = ROOT / "research" / "atlas" / "az-type-registry.json"

IMAGE_BASE = 0x140000000
LOOKUP = 0x1413FB700   # component lookup by AZ type id; args[0] IS an entity
ADD = 0x1413789C0      # append component to an entity;   args[0] IS an entity

# Sanity anchors: the player prefab must show these or we dumped the wrong entity.
SANITY_NAMES = {
    "484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0": "Transform (entity-component)",
    "15407CAA-4970-4D06-8B5C-612FBA11BB45": "CharacterComponent",
}

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe module not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  const codeRanges = mod.enumerateRanges('r-x');

  const MAX_ENTITIES = 16;      // bounded: dump() must never walk the world
  const MAX_ASKED = 400;
  const entities = new Map();   // ptr -> { count, hits, asked:{}, found:{}, lost:{} }
  let lookups = 0, adds = 0, skipped = 0;

  function inCode(p) {
    for (let i = 0; i < codeRanges.length; i++) {
      const r = codeRanges[i];
      if (p.compare(r.base) >= 0 && p.compare(r.base.add(r.size)) < 0) return true;
    }
    return false;
  }

  function fmt(p) {
    const b = new Uint8Array(p.readByteArray(16));
    const h = Array.from(b).map((x) => ('0' + x.toString(16)).slice(-2)).join('');
    return (h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' +
            h.slice(16, 20) + '-' + h.slice(20)).toUpperCase();
  }

  function compCount(p) {
    try {
      const b = p.add(0x10).readPointer();
      const e = p.add(0x18).readPointer();
      if (b.isNull() || e.isNull()) return 0;
      const n = e.sub(b).toInt32();
      if (n < 8 || n % 8 !== 0 || n > 1 << 20) return 0;
      return n / 8;
    } catch (x) { return 0; }
  }

  // Gate BEFORE recording, and cap the set: this is what keeps dump() cheap.
  function track(p) {
    const count = compCount(p);
    if (count < %MINCOMPONENTS%) return null;
    const k = p.toString();
    let e = entities.get(k);
    if (!e) {
      if (entities.size >= MAX_ENTITIES) { skipped++; return null; }
      e = { count: count, hits: 0, asked: {}, found: {}, lost: {} };
      entities.set(k, e);
    }
    e.hits++;
    if (count > e.count) e.count = count;
    return e;
  }

  // All the expensive work happens here, while the client is already inside the
  // call; the JS callback blocks the client's thread, so keep it tiny.
  Interceptor.attach(rva(%LOOKUP%), {
    onEnter(args) {
      lookups++;
      this.e = track(args[0]);
      if (!this.e) return;
      try { this.g = fmt(args[1]); } catch (x) { this.g = null; }
    },
    onLeave(retval) {
      if (!this.e || !this.g) return;
      const e = this.e;
      if (e.asked[this.g] === undefined && Object.keys(e.asked).length < MAX_ASKED) {
        e.asked[this.g] = 0;
      }
      if (e.asked[this.g] !== undefined) e.asked[this.g]++;
      const bucket = retval.isNull() ? e.lost : e.found;
      bucket[this.g] = (bucket[this.g] || 0) + 1;
    }
  });

  Interceptor.attach(rva(%ADD%), { onEnter() { adds++; } });

  function readList(key) {
    const p = ptr(key);
    if (Process.findRangeByAddress(p) === null) return null;
    let begin, end;
    try {
      begin = p.add(0x10).readPointer();
      end = p.add(0x18).readPointer();
    } catch (x) { return null; }
    if (begin.isNull() || end.isNull()) return null;
    const d = end.sub(begin).toInt32();
    if (d < 8 || d % 8 !== 0 || d > 1 << 20) return null;
    return { begin: begin, count: d / 8 };
  }

  // OPT-IN only, and never used unless --mode getters is passed. This calls the
  // same vtable slot 0 that FUN_1413fb700 calls for every component on every
  // lookup; each call is guarded and this is a one-shot pass over one entity.
  function resolveList(key) {
    const info = readList(key);
    if (info === null) return null;
    const out = [], bad = [];
    for (let i = 0; i < info.count; i++) {
      try {
        const comp = info.begin.add(i * 8).readPointer();
        if (comp.isNull()) { bad.push('null'); continue; }
        const vtbl = comp.readPointer();
        if (vtbl.isNull() || !inCode(vtbl)) { bad.push('bad-vtbl'); continue; }
        const fn = vtbl.readPointer();
        if (fn.isNull() || !inCode(fn)) { bad.push('bad-slot0'); continue; }
        const tp = new NativeFunction(fn, 'pointer', ['pointer'])(comp);
        if (tp.isNull()) { bad.push('null-typeid'); continue; }
        out.push(fmt(tp));
      } catch (x) { bad.push('exc'); }
    }
    return { count: info.count, guids: out, bad: bad.length };
  }

  rpc.exports = {
    stats() {
      send({ ev: 'stats', lookups: lookups, adds: adds,
             tracked: entities.size, skipped: skipped });
    },
    // O(tracked), never O(world): everything here was already collected.
    dump() {
      const out = [];
      for (const [key, e] of entities.entries()) {
        out.push({ address: key, count: e.count, hits: e.hits,
                   asked: Object.keys(e.asked), found: Object.keys(e.found),
                   lost: Object.keys(e.lost) });
      }
      out.sort((a, b) => b.count - a.count);
      send({ ev: 'dump', entities: out.slice(0, MAX_ENTITIES) });
    },
    resolve(key) { const r = resolveList(key); send({ ev: 'resolve', address: key, result: r }); }
  };

  send({ ev: 'ready', base: base.toString(16) });
}
"""


def load_registry() -> dict[str, list[str]]:
    """GUID (upper) -> every AZ name registered for it."""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    by_guid: dict[str, list[str]] = {}
    for entry in data["types"]:
        guid = str(entry["guid"]).upper()
        by_guid.setdefault(guid, [])
        if entry["name"] not in by_guid[guid]:
            by_guid[guid].append(entry["name"])
    return by_guid


def physics_guids(by_guid: dict[str, list[str]]) -> dict[str, list[str]]:
    """The physics/rigidbody/controller GUIDs that decide Step 0 (verified values)."""
    pat = re.compile(
        r"Physics|RigidBody|CharacterController|CharacterSupport|Collision",
        re.IGNORECASE,
    )
    return {g: n for g, n in by_guid.items() if any(pat.search(x) for x in n)}


def find_game_pid() -> int | None:
    """Return the pid of NewWorld.exe specifically.

    Do NOT select by window title: `find_windows("New World")` also matches any
    other visible window containing that text -- measured 2026-10-10, it matched a
    browser tab titled "Azoth - Servidor privado de New World". Attaching Frida to
    that process would probe the wrong thing and report nothing useful.
    """
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == "newworld.exe":
            return proc.pid
    return None


def wait_for_game(wait: float) -> int | None:
    deadline = time.time() + wait
    while time.time() < deadline:
        pid = find_game_pid()
        if pid is not None:
            return pid
        time.sleep(2)
    return None


def summarise(dump: dict, by_guid: dict[str, list[str]], phys: dict[str, list[str]]) -> dict:
    asked = set(dump["asked"])
    found = set(dump["found"])
    lost = set(dump["lost"])
    name = lambda g: by_guid.get(g, [g])[0]  # noqa: E731
    return {
        "address": dump["address"],
        "components": dump["count"],
        "hits": dump["hits"],
        "asked": len(asked),
        "found": len(found),
        "sanity": {SANITY_NAMES[g]: (g in asked) for g in SANITY_NAMES},
        "physics_asked": {name(g): ("FOUND" if g in found else "null") for g in phys if g in asked},
        "physics_never_asked": [name(g) for g in phys if g not in asked][:12],
        "asked_named": sorted(name(g) for g in asked if g in by_guid),
        "asked_unnamed": sorted(g for g in asked if g not in by_guid),
        "lost_named": sorted(name(g) for g in lost if g in by_guid),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--wait", type=float, default=400.0,
                    help="seconds to wait for NewWorld.exe before giving up")
    ap.add_argument("--interval", type=int, default=20, help="seconds between dumps")
    ap.add_argument("--mode", choices=("hooks", "getters"), default="hooks",
                    help="hooks = read arguments only (safe); getters also calls "
                         "each component's type-id getter (invokes client code)")
    ap.add_argument("--min-components", type=int, default=32,
                    help="only track entities with at least this many components")
    args = ap.parse_args()

    pid = wait_for_game(args.wait)
    if pid is None:
        print(f"NewWorld.exe not running after {args.wait:.0f}s", flush=True)
        return 1
    print(f"attaching to NewWorld.exe pid {pid}", flush=True)

    by_guid = load_registry()
    phys = physics_guids(by_guid)

    out_path = probe_capture(f"player-components-{int(time.time())}.jsonl")
    out = out_path.open("a", encoding="utf-8")

    session = frida.attach(pid)
    script = session.create_script(
        JS.replace("%LOOKUP%", hex(LOOKUP))
        .replace("%ADD%", hex(ADD))
        .replace("%MINCOMPONENTS%", str(args.min_components))
    )

    best: dict | None = None
    resolved = False
    target: str | None = None

    def on_dump(payload: dict) -> None:
        nonlocal best, target
        ents = payload.get("entities", [])
        if not ents:
            return
        top = ents[0]
        rep = summarise(top, by_guid, phys)
        target = rep["address"]
        if rep["sanity"].get("Transform (entity-component)"):
            print(
                f"[components] PLAYER candidate {rep['address']} n={rep['components']} "
                f"lookups={rep['hits']} asked={rep['asked']} found={rep['found']}",
                flush=True,
            )
            print(f"[components] named: {rep['asked_named']}", flush=True)
            if rep["physics_asked"]:
                print(f"[components] PHYSICS: {rep['physics_asked']}", flush=True)
            else:
                print("[components] PHYSICS: none of the physics ids were asked about",
                      flush=True)
        if best is None or rep["components"] >= best["components"]:
            best = dict(rep)
        out.write(json.dumps({"top": rep, "all": [e["count"] for e in ents]}) + "\n")
        out.flush()

    def on_message(message, _data):
        if message.get("type") == "send":
            payload = message["payload"]
            ev = payload.get("ev")
            if ev == "ready":
                print(f"[components] hooks live base={payload['base']}", flush=True)
            elif ev == "stats":
                print(
                    f"[components] stats lookups={payload['lookups']} adds={payload['adds']} "
                    f"tracked={payload['tracked']} skipped={payload['skipped']}",
                    flush=True,
                )
            elif ev == "dump":
                on_dump(payload)
            elif ev == "resolve":
                res = payload.get("result")
                print(f"[components] full list for {payload['address']}: {res}", flush=True)
                out.write(json.dumps({"resolve": payload}) + "\n")
                out.flush()
            elif ev == "error":
                print(f"[components] ERROR {payload}", flush=True)
        elif message.get("type") == "error":
            print("script error:", message.get("description", "")[:400], flush=True)

    script.on("message", on_message)
    script.load()
    print(f"[components] logging to {out_path}", flush=True)

    deadline = time.time() + args.timeout
    next_dump = time.time() + 15
    try:
        while time.time() < deadline:
            if time.time() >= next_dump:
                next_dump = time.time() + args.interval
                script.exports_sync.stats()
                script.exports_sync.dump()
                if args.mode == "getters" and target and not resolved:
                    resolved = True
                    print(f"[components] resolving the full list of {target} (getters)", flush=True)
                    script.exports_sync.resolve(target)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            script.exports_sync.stats()
            script.exports_sync.dump()
        except Exception as exc:  # noqa: BLE001 - the target may already be gone
            print(f"[components] final dump failed: {exc}", flush=True)
        session.detach()
        out.close()

    if best is not None:
        print("\n[components] summary for the largest tracked entity:")
        print(json.dumps(best, indent=1)[:4000])
        verdict = "present" if any(v == "FOUND" for v in best["physics_asked"].values()) else "absent/never asked"
        print(f"\n[components] STEP 0 verdict: a physics component is {verdict}")
    else:
        print("[components] no entity reached --min-components; the world load was missed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
