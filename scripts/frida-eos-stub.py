#!/usr/bin/env python3
"""Stub the EOS AntiCheat ClientSDK resolver (Frida, OUR runtime).

1.400 ClientSDK dynamically resolves EOS_AntiCheatClient_* via
FUN_1444f79e0. EOSSDK.dll is not loaded on the private runtime, so
GetProcAddress fails and registration dies as
@mm_csdkerr_server_requires_anticheat / @eos_unknown_error 4ms after
the REP socket comes up.

This replaces the resolver: every Get*Interface / Create slot returns a
fake handle; BeginSession/EndSession/Initialize/Tick return EOS_Success
(0). The script MUST stay attached (NativeCallbacks die on detach).
"""

from __future__ import annotations

import time

import frida

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { throw new Error('no NewWorld.exe'); }
const base = mod.base;
const off = (va) => va.sub(ptr('0x140000000'));
console.log('[eos-stub] base ' + base);

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
    console.log('[eos-stub] BeginSession -> EOS_Success');
    return 0;
}, 'int', ['pointer', 'pointer', 'pointer', 'pointer']);

// FUN_1444f79e0: resolve EOS exports into obj+0x08..
const resolver = base.add(off(ptr('0x1444F79E0')));
Interceptor.replace(resolver, new NativeCallback(function (obj) {
    // offsets from the lea-chain in FUN_1444f79e0 (string order)
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
    console.log('[eos-stub] resolver filled obj=' + obj);
    return 1;
}, 'int', ['pointer']));
console.log('[eos-stub] FUN_1444f79e0 replaced');
send('ready');
"""


def main() -> int:
    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        print("NewWorld.exe not running")
        return 1
    ready: list[str] = []
    script = session.create_script(JS)
    script.on(
        "message",
        lambda m, _d: (
            ready.append("ok")
            if m.get("type") == "send"
            else print(m)
        ),
    )
    script.load()
    for _ in range(20):
        if ready:
            break
        time.sleep(0.1)
    if not ready:
        print("[eos-stub] script did not signal ready")
        return 1
    print("[eos-stub] active — leave this window open, then click Jugar")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
