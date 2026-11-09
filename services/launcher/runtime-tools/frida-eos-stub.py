#!/usr/bin/env python3
"""Stub the EOS AntiCheat ClientSDK resolver (Frida, OUR runtime).

The ClientSDK resolves every `EOS_AntiCheatClient_*` export through one
resolver function: `FUN_1444f79e0` on 1.400, `FUN_1444f8b20` on 1.460. EOSSDK.dll
is not loaded on the private runtime, so GetProcAddress fails and registration
dies as `@mm_csdkerr_server_requires_anticheat` / `@eos_unknown_error` 4 ms after
the REP socket comes up.

This replaces the resolver: every Get*Interface / Create slot returns a fake
handle; BeginSession/EndSession/Initialize/Tick return EOS_Success (0). The
script MUST stay attached (NativeCallbacks die on detach).

BUILD IDENTITY (2026-11-09). The resolver is looked up by the SHA-256 of the
executable and its prologue is byte-checked before the replace, so a build that
moves the function stops this tool instead of writing into the wrong instruction.
The 1.400 VA `0x1444F79E0` is deliberately NOT a row here: on 1.460 those bytes
are a `call qword [rip+0x39d2a1a]` inside another function, and replacing that
instruction killed the client at `Initializing Render Module RenderD3D12`
(0xc0000005, ntdll+0x166447, measured 2026-11-09). A 1.400 lab would have to
re-derive its prologue from the corpus before adding the row.

The transform-registration and slice-probe hooks that used to live in this file
were all 1.400 VAs. On 1.460 every one of them lands mid-instruction (measured
2026-11-09), so they are gone; their measured results stay in
`research/atlas/client-functions.json`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_sites  # noqa: E402
from build_sites import BUILD_1_460, Site  # noqa: E402

TAG = "eos-stub"
LOG = Path(__file__).resolve().parents[3] / ".azoth" / "logs" / "eos-stub.log"

# `mov [rsp+0x18],rbx; push rsi; sub rsp,0x20; mov rbx,rcx; lea rdx,[rip+X]`
# is the body of FUN_1444f8b20 as read from the executable on 2026-11-09.
RESOLVER_PROLOGUE = bytes.fromhex("48 89 5C 24 18 56 48 83 EC 20 48 8B D9 48 8D 15 3C 67 E5 03")

SITES: dict[str, tuple[Site, ...]] = {
    # `want` equals `orig`: this site is replaced in memory by Frida, not
    # written, so the shared check only has to prove the prologue is present.
    BUILD_1_460: (
        Site(0x1444F8B20, RESOLVER_PROLOGUE, RESOLVER_PROLOGUE, "EOS ClientSDK resolver"),
    ),
}

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { throw new Error('no NewWorld.exe'); }
const base = mod.base;
const off = (va) => va.sub(ptr('0x140000000'));
send('[eos-stub] base ' + base);

const fake = Memory.alloc(0x100);
fake.writeU64(0xA2011100);

const ret0 = new NativeCallback(function () { return 0; }, 'int', ['pointer', 'pointer', 'pointer', 'pointer']);
const retNotify = new NativeCallback(function () {
    // EOS_INVALID_NOTIFICATIONID is 0 — returning 0 made AddNotify
    // look like it failed, then ClientSDK waited ~2.7s and raised
    // @eos_unknown_error (Game.log 2026-09-18 18:18:55→57).
    return 1;
}, 'uint64', ['pointer', 'pointer', 'pointer', 'pointer']);
const retH = new NativeCallback(function () { return fake; }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
const begin = new NativeCallback(function () {
    send('[eos-stub] BeginSession -> EOS_Success');
    return 0;
}, 'int', ['pointer', 'pointer', 'pointer', 'pointer']);

// FUN_1444f8b20: resolve EOS exports into obj+0x08..
const resolver = base.add(off(ptr('0x%RESOLVER_VA%')));
const prologue = [%PROLOGUE%];
const before = new Uint8Array(resolver.readByteArray(prologue.length));
for (let i = 0; i < prologue.length; i++) {
    if (before[i] !== prologue[i]) {
        throw new Error('[eos-stub] REFUSING: resolver prologue mismatch at ' +
                        resolver + ' got ' + before.toString());
    }
}
Interceptor.replace(resolver, new NativeCallback(function (obj) {
    // offsets from the lea-chain in the resolver (string order)
    const slots = {
        0x08: retNotify,  // AddNotifyMessageToServer
        0x10: begin,      // BeginSession
        0x18: ret0,       // EndSession
        0x20: ret0,       // ReceiveMessageFromServer
        0x28: retH,       // GetAntiCheatClientInterface
        0x30: retH,       // GetAntiCheatServerInterface
        0x38: retH,       // GetConnectInterface
        0x40: ret0,       // Platform_Tick
        0x48: retH,       // Platform_Create
        0x50: ret0,       // Initialize
        0x58: ret0,       // Shutdown
        0x60: ret0,       // Platform_Release
        0x68: ret0,       // Logging_SetLogLevel
        0x70: ret0,       // Logging_SetCallback
        0x78: ret0,       // Connect_CreateUser
        0x80: ret0,       // Connect_Login
        0x88: retNotify,  // AddNotifyClientIntegrityViolated
    };
    for (const [offStr, fn] of Object.entries(slots)) {
        obj.add(parseInt(offStr)).writePointer(fn);
    }
    send('[eos-stub] resolver filled obj=' + obj);
    return 1;
}, 'int', ['pointer']));
send('[eos-stub] resolver replaced at ' + resolver);
send('ready');
"""


def _log(line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    text = f"{stamp} {line}\n"
    print(text, end="", flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="static prologue report from disk; never attaches")
    args = ap.parse_args()

    if args.check:
        return build_sites.report_check(SITES, TAG)

    # The launcher starts this hidden and detached, so stdout reaches nobody.
    # The first line must exist before attach: it proves the process started
    # and when, which is the difference between "the stub never ran" and
    # "the stub ran and the client died under it" (measured 2026-11-09).
    _log(f"[eos-stub] start pid={os.getpid()} exe={build_sites.private_exe()}")
    build, exe, note = build_sites.identify(SITES)
    site = SITES[build][0]
    print(f"[{TAG}] build sha256={build}")
    print(f"[{TAG}] {note}")
    print(f"[{TAG}] resolver va={site.va:#x} expected={site.orig.hex()} in {exe}")

    import frida  # slow import; keep --check usable without a Frida session

    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        _log("[eos-stub] NewWorld.exe not running")
        return 1
    _log("[eos-stub] attached")

    ready: list[str] = []
    failed: list[str] = []

    def on_message(message: dict, _data: object) -> None:
        if message.get("type") == "error":
            failed.append(str(message.get("description")))
        if message.get("type") == "send" and message.get("payload") == "ready":
            ready.append("ok")
        text = message.get("payload")
        if text is None:
            text = message.get("description") or message.get("stack") or message
        _log(f"{message.get('type')} {text}")

    js = JS.replace("%RESOLVER_VA%", f"{site.va:X}".lower())
    js = js.replace("%PROLOGUE%", ",".join(str(b) for b in RESOLVER_PROLOGUE))
    script = session.create_script(js)
    script.on("message", on_message)
    try:
        script.load()
    except frida.TransportError:
        pass  # a script-level error is reported through on_message first
    for _ in range(20):
        if ready or failed:
            break
        time.sleep(0.1)
    if failed:
        # Never leave a half-loaded script attached: the client faults later.
        session.detach()
        _log(f"[eos-stub] load failed: {failed[0]}")
        return 1
    if not ready:
        session.detach()
        _log("[eos-stub] script did not signal ready")
        return 1
    _log("[eos-stub] active — leave this process running, then click Jugar")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
