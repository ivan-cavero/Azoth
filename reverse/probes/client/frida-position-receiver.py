#!/usr/bin/env python3
"""Does the client ever create or register an IPositionReceiver instance?

WHY. The position reply cannot be applied until a client-side RMI target answers
`IPositionReceiver`. Measured 2026-10-11/12: none does (37063 registered targets, 225
distinct vtables, 0 positives), and `StartMovementCommunicationMsg` sent reliably on
channel 0 does not change that.

Static 2026-10-12 located the machinery (atlas `ipositionreceiver_vtable_layout_20261012`):
the interface vtable `0x1482eb160` is referenced by exactly ONE site in the whole image,
the installer `0x143f983d0` (`lea rax,[0x1482eb160]; mov [r8],rax`), which is reached as
slot +0x28 of the family's base vtable `0x1482ea4e8`; the interface is registered by name
by `0x143f98300` (leas the string `IPositionReceiver` and calls a registry method). Neither
has a direct caller, so both are invoked through the data-driven AZ reflection descriptor
at `0x1482ea4e8`. That means the creation cannot be found by following xrefs - it has to be
observed. This probe observes it.

WHAT IT REPORTS (all read-only):
  * whether `0x143f983d0` (installer) ever runs after attach -> an interface instance was
    created, with the caller's return address;
  * whether `0x143f98300` (register-by-name) ever runs after attach, with the name string
    it passes, so a registration of IPositionReceiver is caught by name;
  * the AZ reflection registry object, read from the global `[rip+0x637bce0]` at
    0x143f98311, with the function pointer it would call, so the registry can be identified
    in a later pass;
  * the delivery counters (`FUN_143f97bf0`) as a control, so "nothing fired" is
    distinguishable from "the probe was not live".

INTERPRETATION. If neither hook fires during a whole login + world entry, then our session
never creates the receiver, and the missing piece is upstream in the client's object graph
(consistent with `replay_sends_to_unbound_client_facets_20261012`). If the installer fires,
its backtrace names the creating code and the next step is to make that code run earlier or
at all.

Attach BEFORE world entry. Read-only, private no-EAC client.

Usage:
  python az.py probe frida-position-receiver --timeout 900 --poll 10
"""

from __future__ import annotations

import argparse
import json
import time

import frida

from _paths import probe_capture

INSTALLER = 0x143F983D0    # stamps vtable 0x1482eb160 onto an interface sub-object
REGISTER = 0x143F98300     # registers the interface by name ("IPositionReceiver")
DELIVER = 0x143F97BF0      # delivery: control counter
# [rip+0x637bce0] at 0x143f98311: the lazily-created AZ interface-reflection registry.
# 0x143f98318 (next instruction) + 0x637bce0 = 0x14a313ff8, in .data.
REGISTRY_GLOBAL = 0x14A313FF8

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (mod === null) {
  send({ ev: 'error', error: 'NewWorld.exe not found' });
} else {
  const base = mod.base;
  const rva = (v) => base.add(v - 0x140000000);
  let installs = 0, registers = 0, deliver = 0;
  let registryHookInstalled = false;
  let registryHookFn = null;
  const registryNames = [];
  const installSites = [];
  const registerNames = [];
  const registerSites = [];

  function nameAt(p) {
    try { return p.readUtf8String(64); } catch (e) { return null; }
  }

  try {
    Interceptor.attach(rva(0x143f983d0), {
      onEnter(args) {
        installs++;
        // r8 is the out-parameter the vtable is written to; rdx is the sub-object.
        let out = null, sub = null;
        try { out = args[2] ? args[2].toString() : null; } catch (e) {}
        try { sub = args[1] ? args[1].toString() : null; } catch (e) {}
        if (installSites.length < 32) {
          installSites.push({
            t: Date.now(), out: out, sub: sub,
            ra: this.returnAddress.sub(base).toString(16),
          });
        }
        send({ ev: 'installer-fired', out: out, sub: sub,
               ra: this.returnAddress.sub(base).toString(16) });
      },
    });
  } catch (e) { send({ ev: 'error', hook: 'installer', error: String(e) }); }

  try {
    Interceptor.attach(rva(0x143f98300), {
      onEnter(args) {
        registers++;
        // The name string is loaded at 0x143f983a0 into rdx; at entry we can read the
        // hardcoded address directly since this function always registers the same type.
        const name = nameAt(rva(0x1482ea920));
        const ra = this.returnAddress.sub(base).toString(16);
        registerNames.push({ t: Date.now(), name: name, ra: ra });
        registerSites.push(ra);
        send({ ev: 'register-fired', name: name, ra: ra });
      },
    });
  } catch (e) { send({ ev: 'error', hook: 'register', error: String(e) }); }

  try {
    Interceptor.attach(rva(0x143f97bf0), { onEnter() { deliver++; } });
  } catch (e) { send({ ev: 'error', hook: 'deliver', error: String(e) }); }

  rpc.exports = {
    // Read the registry and hook its register-by-name method, so EVERY interface
    // registered from now on is observed by name. Done from Python, never from inside a
    // hook callback. Returns what it found so "registered before attach" stays
    // distinguishable from "never registered".
    hookRegistry() {
      if (registryHookInstalled) return { installed: true, fn: registryHookFn };
      try {
        const g = rva(0x14a313ff8).readPointer();
        if (g.isNull()) return { installed: false, reason: 'registry global is null' };
        const vt = g.add(0x30).readPointer();
        const fn = vt.add(8).readPointer();
        registryHookFn = fn.toString();
        Interceptor.attach(fn, {
          onEnter(args) {
            // The name is NOT in a register: the caller builds an {ptr,len} pair on its own
            // stack (0x143f983a0 loads the string, then stores it at [rsp+0x20] before the
            // call). Capture the raw context and the first stack qwords, and try each qword
            // as a C string, so the pointer is identified rather than guessed.
            const ctx = this.context;
            const raw = [];
            for (let i = 0; i < 8; i++) {
              try { raw.push(ctx.rsp.add(i * 8).readU64().toString()); } catch (e) { raw.push(null); }
            }
            const strs = [];
            for (const q of raw) {
              if (q === null) { strs.push(null); continue; }
              try {
                const p = ptr(q);
                if (Process.findRangeByAddress(p) === null) { strs.push(null); continue; }
                const s = p.readUtf8String(80);
                strs.push(s && s.length > 2 ? s : null);
              } catch (e) { strs.push(null); }
            }
            const rec = {
              t: Date.now(),
              rcx: ctx.rcx.toString(), rdx: ctx.rdx.toString(),
              r8: ctx.r8.toString(), r9: ctx.r9.toString(),
              ra: this.returnAddress.sub(base).toString(16),
              stack: raw, strings: strs,
            };
            registryNames.push(rec);
            send({ ev: 'registry-register', ra: rec.ra, strings: strs });
          },
        });
        registryHookInstalled = true;
        return { installed: true, fn: registryHookFn, names: registryNames.length };
      } catch (e) { return { installed: false, reason: String(e) }; }
    },
    stats() {
      let registry = null, regVtable = null, regFn = null;
      try {
        const g = rva(0x14a313ff8).readPointer();
        registry = g.toString();
        if (!g.isNull()) {
          const vt = g.add(0x30).readPointer();
          regVtable = vt.toString();
          regFn = vt.add(8).readPointer().toString();
        }
      } catch (e) { registry = 'read-error: ' + String(e); }
      return {
        installer_fired: installs,
        register_fired: registers,
        deliver_calls: deliver,
        install_sites: installSites.slice(-8),
        register_names: registerNames.slice(-8),
        registry_global: registry,
        registry_vtable: regVtable,
        registry_call: regFn,
        registry_hook_installed: registryHookInstalled,
        registry_hook_fn: registryHookFn,
        registry_names_seen: registryNames.slice(-24),
      };
    },
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--poll", type=float, default=10.0)
    ap.add_argument("--process", default="NewWorld.exe")
    ap.add_argument("--with-registry", action="store_true",
                    help="also hook the AZ reflection registry method. It is a GENERIC "
                         "method (it fires from many unrelated callers), so it is opt-in to "
                         "keep the probe's footprint minimal in a run whose point is the "
                         "cold installer/register counters.")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.process)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("[pr]", json.dumps(m), flush=True))
    script.load()
    print(f"[pr] attached to {args.process}", flush=True)

    capture = probe_capture(f"position-receiver-{int(time.time())}.jsonl")
    print(f"[pr] live -> {capture}", flush=True)

    end = time.time() + args.timeout
    hooked = not args.with_registry
    with capture.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            try:
                if not hooked and args.with_registry:
                    res = script.exports_sync.hook_registry()
                    print(f"[pr] hookRegistry -> {json.dumps(res)}", flush=True)
                    hooked = bool(res.get("installed"))
                st = script.exports_sync.stats()
            except Exception as exc:  # noqa: BLE001
                print(f"[pr] status error: {exc}", flush=True)
                time.sleep(2.0)
                continue
            fh.write(json.dumps({"t": time.time(), **st}) + "\n")
            fh.flush()
            print(
                f"[pr] installer={st['installer_fired']} register={st['register_fired']} "
                f"deliver={st['deliver_calls']} registry={st['registry_global']} "
                f"hook={st['registry_hook_installed']} names={len(st['registry_names_seen'])}",
                flush=True,
            )
            time.sleep(args.poll)

    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    print(f"[pr] done; capture {capture}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
