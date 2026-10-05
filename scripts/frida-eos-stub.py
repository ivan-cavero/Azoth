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

import json
import os
import re
import time
from pathlib import Path

import frida

# The launcher starts this hidden, so console.log never reaches a window.
# The registration line is the only proof the hook ran before the clone.
_LOG = Path(os.environ.get("LOCALAPPDATA", ".")) / "Temp" / "azoth-eos-stub.log"


def _log(line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    text = f"{stamp} {line}\n"
    print(text, end="", flush=True)
    with _LOG.open("a", encoding="utf-8") as handle:
        handle.write(text)

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
    send('[eos-stub] resolver filled obj=' + obj);
    return 1;
}, 'int', ['pointer']));
send('[eos-stub] FUN_1444f79e0 replaced');

// GameTransformComponent is dropped unless FUN_141582430 runs while the
// SerializeContext gate byte at +8 is still 0 (movzx eax,[rcx+8]; ret at
// 0x140ecc130). By the time the slice cloner runs, that byte is already 1
// and the registrar only looks the class up. Clear it for the call, then
// put it back. Once per context. This process's already-built entities
// are not rebuilt; the hook has to be in place before the next instantiate.
const CTX_VT = base.add(0x7FE8F30);
const registerTransform = new NativeFunction(
    base.add(0x1582430), 'pointer', ['pointer', 'pointer', 'pointer'], 'win64');
const seenCtx = Object.create(null);
const seenVt = Object.create(null);
let vtLogs = 0;
// H1 (activity_stream follow-up): the world-load clone may pass a
// SerializeContext with a DIFFERENT vtable than CTX_VT; registering only on
// CTX_VT could miss the one the slice cloner actually uses. Log EVERY distinct
// context vtable the cloner sees during load (with the +8 gate byte) so the
// next symbols entry can name the real one. Registration stays CTX_VT-only:
// calling FUN_141582430 on a non-SerializeContext object is unvalidated.
const VT_LOG_CAP = 64;
Interceptor.attach(base.add(0x13F8CF0), {
    onEnter(args) {
        const ctx = args[0];
        if (ctx.isNull()) return;
        const key = ctx.toString();
        if (seenCtx[key]) return;
        let vt;
        try { vt = ctx.readPointer(); } catch (e) { return; }
        if (!vt.equals(CTX_VT)) {
            const vs = vt.toString();
            if (!seenVt[vs]) {
                seenVt[vs] = 0;
            }
            seenVt[vs]++;
            if (vtLogs < VT_LOG_CAP) {
                vtLogs++;
                let flag = 'err';
                try { flag = ctx.add(8).readU8(); } catch (e) {}
                send('[eos-stub] cloner other vt=' + vt + ' ctx=' + ctx +
                     ' flag=' + flag + ' hits=' + seenVt[vs]);
            }
            return;
        }
        seenCtx[key] = true;
        let flag = 0;
        try { flag = ctx.add(8).readU8(); } catch (e) { flag = 0; }
        const forced = flag !== 0;
        if (forced) {
            try { ctx.add(8).writeU8(0); }
            catch (e) {
                delete seenCtx[key];
                send('[eos-stub] GameTransform flag clear failed ' + e);
                return;
            }
        }
        try {
            const out = Memory.alloc(0x20);
            registerTransform(ctx, out, base.add(0x9E90CF8));
            send('[eos-stub] GameTransform registered ctx=' + ctx + ' flag=' + flag + ' forced=' + forced);
        } catch (e) {
            delete seenCtx[key];
            send('[eos-stub] GameTransform register failed ' + e);
        } finally {
            if (forced) {
                try { ctx.add(8).writeU8(flag); } catch (e) {}
            }
        }
    }
});

// Two functions write the same "Couldn't get Transform component" warning:
// FUN_1416797d0 (the call at RVA 0x1679A5C, return 0x1679A61) and
// FUN_1417880b0 (call at RVA 0x17882CC, return 0x17882D1). Both verified in
// the exe as E8 rel32 -> FUN_1413FB700 (RVA 0x13FB700) with the GameTransform
// type id from FUN_141048c60; both log when that lookup returns NULL.
// The slice name is a small-string std::string inside the job at +0x110
// (size +0x120, capacity +0x128, heap pointer at +0x110 when capacity > 15);
// +0x30 and +0x70 carry two more scope names with the same layout.
// The tick runs for every slice, so the add is gated on the resolved name and
// on 40 entities: the earlier unfiltered hook attached ~12000 components and
// the client dropped with @mm_csdkerr_disconnect.
const createTransform = new NativeFunction(base.add(0x169A210), 'pointer', [], 'win64');
const addComponent = new NativeFunction(
    base.add(0x13789C0), 'int', ['pointer', 'pointer'], 'win64');
const RET_A = base.add(0x1679A61);
const RET_B = base.add(0x17882D1);
const STR_OFFS = [0x110, 0x30, 0x70];
// OFF by default. The 2026-10-03 A/B with this attach on attached 40
// components, left 15 warnings, and the client then died with an access
// violation (0x3F00CE4) right after OnLocalNetworkConnectionWarning. The
// logging is what we want on a baseline run; the attach is a separate
// experiment, so it needs AZOTH_TRANSFORM_ATTACH=1 on the launcher.
const ATTACH_ENABLED = __ATTACH_ENABLED__;
const addedEnt = Object.create(null);
let attachBusy = false;
let attachSkips = 0;
let attachCount = 0;
let remoteDepth = 0;
let capLogged = false;
const ATTACH_CAP = 40;
const NAME_LOGS = { A: 0, B: 0 };
const MAX_NAME_LOGS = 8;
let currentJobName = '?';
let currentJobBName = '?';

function printable(s) {
    if (!s) return false;
    for (let i = 0; i < s.length; i++) {
        const c = s.charCodeAt(i);
        if (c < 0x20 || c > 0x7e) return false;
    }
    return true;
}
function readStringAt(at) {
    let size = 0;
    let cap = 0;
    try {
        size = at.add(0x10).readU64().toNumber();
        cap = at.add(0x18).readU64().toNumber();
    } catch (e) {
        return null;
    }
    if (size === 0 || size > 260) return null;
    // capacity > 15 is the MSVC/AZStd heap form; try both when the first
    // interpretation is not printable text.
    const modes = cap > 15 ? [true, false] : [false, true];
    for (let i = 0; i < modes.length; i++) {
        try {
            const src = modes[i] ? at.readPointer() : at;
            if (src.isNull()) continue;
            const s = src.readUtf8String(size);
            if (printable(s)) return s;
        } catch (e) {}
    }
    return null;
}
function jobNames(job) {
    const found = [];
    for (let i = 0; i < STR_OFFS.length; i++) {
        const o = STR_OFFS[i];
        const s = readStringAt(job.add(o));
        if (s) found.push('+0x' + o.toString(16) + '=' + s);
    }
    return found;
}
function hookJob(tag, rva) {
    Interceptor.attach(base.add(rva), {
        onEnter(args) {
            this.remote = false;
            const job = args[0];
            if (job.isNull()) return;
            let names = [];
            try { names = jobNames(job); } catch (e) {}
            let remote = false;
            for (let i = 0; i < names.length; i++) {
                if (names[i].toLowerCase().indexOf('remoteplayer') !== -1) remote = true;
            }
            if (names.length) {
                const nm = names.join(' | ');
                if (tag === 'A') currentJobName = nm;
                else currentJobBName = nm;
            }
            if (NAME_LOGS[tag] < MAX_NAME_LOGS) {
                NAME_LOGS[tag]++;
                if (names.length) {
                    send('[eos-stub] ' + tag + (remote ? ' MATCH' : '') + ' job ' + names.join(' | '));
                } else {
                    let hex = '';
                    try {
                        const bytes = new Uint8Array(job.add(0x110).readByteArray(0x20));
                        for (let i = 0; i < bytes.length; i++) hex += ('0' + bytes[i].toString(16)).slice(-2);
                    } catch (e) {}
                    send('[eos-stub] ' + tag + ' job no-name +110=' + hex);
                }
            }
            if (remote) {
                this.remote = true;
                remoteDepth++;
                send('[eos-stub] ' + tag + ' remote slice depth=' + remoteDepth);
            }
        },
        onLeave() {
            if (this.remote && remoteDepth > 0) remoteDepth--;
        }
    });
}
hookJob('A', 0x16797D0);  // FUN_1416797d0, warn return 0x1679A61
hookJob('B', 0x17880B0);  // FUN_1417880b0, warn return 0x17882D1

// Count every lookup that returns to either warning site, remote or not.
const HIT_MARKS = [1, 26, 100, 1000];
let hitsA = 0;
let hitsB = 0;
Interceptor.attach(base.add(0x13FB700), {
    onEnter(args) {
        const ra = this.returnAddress;
        let tag = null;
        if (ra.equals(RET_A)) tag = 'A';
        else if (ra.equals(RET_B)) tag = 'B';
        if (tag === 'A') {
            hitsA++;
            if (HIT_MARKS.indexOf(hitsA) !== -1) send('[eos-stub] hits A=' + hitsA);
        } else if (tag === 'B') {
            hitsB++;
            if (HIT_MARKS.indexOf(hitsB) !== -1) send('[eos-stub] hits B=' + hitsB);
        }
        if (!ATTACH_ENABLED || attachBusy || remoteDepth === 0 || tag === null) return;
        if (attachCount >= ATTACH_CAP) {
            if (!capLogged) {
                capLogged = true;
                send('[eos-stub] attach cap ' + ATTACH_CAP + ' reached, stop adding');
            }
            return;
        }
        const entity = args[0];
        if (entity.isNull()) return;
        const key = entity.toString();
        if (addedEnt[key]) return;
        let state;
        try { state = entity.add(0x60).readU8(); } catch (e) { return; }
        if (state !== 0) {
            // state 2 means AddComponent would call vtable+0x50 (Activate),
            // which is the path that dropped the client before. Never take it.
            if (attachSkips < 12) {
                attachSkips++;
                send('[eos-stub] transform skip state=' + state + ' tag=' + tag + ' ent=' + entity);
            }
            return;
        }
        attachBusy = true;
        try {
            const comp = createTransform();
            if (comp.isNull()) {
                send('[eos-stub] transform alloc failed ent=' + entity);
                return;
            }
            const ok = addComponent(entity, comp);
            if (ok) {
                addedEnt[key] = true;
                attachCount++;
                send('[eos-stub] transform attached ent=' + entity + ' tag=' + tag +
                     ' state=' + state + ' n=' + attachCount);
            } else {
                const vt = comp.readPointer();
                const release = new NativeFunction(
                    vt.add(0x30).readPointer(), 'void', ['pointer', 'uint64'], 'win64');
                release(comp, 1);
                send('[eos-stub] transform add rejected ent=' + entity + ' tag=' + tag +
                     ' state=' + state);
            }
        } catch (e) {
            send('[eos-stub] transform attach failed ' + e);
        } finally {
            attachBusy = false;
        }
    }
});
// READ-ONLY probe of the body/transform creation path. No attach.
// Question: which of these actually run in a real session, and from where?
//   FUN_14169a210 (RVA 0x169A210) = the GameTransformComponent factory
//       (allocates 0x210, runs the ctor FUN_14161b9b0).
//   FUN_141582430 (RVA 0x1582430) = the SerializeContext creator for
//       GameTransformComponent.
//   FUN_141763b70 (RVA 0x1763B70) = the gate that resolves an entity and then
//       calls FUN_141582430; shard-000312.c:3479.
//   FUN_1413f8cf0 (RVA 0x13F8CF0) = the cloner the stub already watches.
function probe(tag, rva, argCount, perLog) {
    let calls = 0;
    Interceptor.attach(base.add(rva), {
        onEnter(args) {
            calls++;
            if (calls <= perLog) {
                let extra = '';
                for (let i = 0; i < argCount; i++) {
                    try { extra += ' a' + i + '=' + args[i]; } catch (e) {}
                }
                send('[probe] ' + tag + ' #' + calls + ' from=' + this.returnAddress + extra);
            }
        }
    });
    return function () { return calls; };
}
const factoryCalls = probe('factory FUN_14169a210', 0x169A210, 0, 6);
const creatorCalls = probe('creator FUN_141582430', 0x1582430, 2, 6);
const gateCalls = probe('gate FUN_141763b70', 0x1763B70, 1, 8);
const clonerCalls = probe('cloner FUN_1413f8cf0', 0x13F8CF0, 1, 4);
// The LevelInfoChanged handler decides whether this client is the MASTER
// player. At 0x146446C45 it does `movzx eax, byte [r13]` and stores that byte,
// and the sibling branch at 0x146446C52 logs
// 'LevelInfoChanged javContext.IsMasterPlayer is false'. A false master flag
// means the client treats its own actor as a remote replica, which would
// explain both the missing local body and the 26 remoteplayer slice warnings.
let masterReads = 0;
const masterValues = Object.create(null);
Interceptor.attach(base.add(0x6446C45), {
    onEnter() {
        masterReads++;
        let v = 'err';
        try { v = this.context.r13.readU8(); } catch (e) {}
        masterValues[v] = (masterValues[v] || 0) + 1;
        if (masterReads <= 8) send('[probe] master byte=' + v + ' read#' + masterReads);
    }
});
const masterFalseLogsInit = 0;
// Count the two functions that would create a physics component on an entity:
// the local player has 124 components (transform, CharacterComponent,
// Inventories, CameraLock, PlayerInputFilters...) but NO physics component at
// all, and without a physics body nothing can move the character. That is why
// WASD does nothing while mouse look (camera) works and the input system does
// receive the key. FUN_141761dd0 is the by-name component cluster and
// FUN_1416951b0 is the GameRigidBodyClientFacetConfig factory it calls.
const clusterCalls = probe('cluster FUN_141761dec', 0x1761DEC, 1, 8);
const rbConfigCalls = probe('rigidbody-config FUN_1416951b0', 0x16951B0, 1, 8);
// The single funnel for every component that ends up on an entity is
// FUN_1413789c0 = AZ::Entity::AddComponent(entity, comp). Log what is added and
// to whom, resolved through the Name<->uuid table read out of .rdata: this says
// whether a GameRigidBody* component is ever created, and for which entity.
const NAMES = __NAMES__;
let addCalls = 0;
const addByEntity = Object.create(null);
const addIds = Object.create(null);
Interceptor.attach(base.add(0x13789C0), {
    onEnter(args) {
        addCalls++;
        const ent = args[0];
        let id = 'err';
        try {
            const c = args[1];
            const vt = c.readPointer();
            const fn = vt.readPointer();
            const p = new NativeFunction(fn, 'pointer', ['pointer'], 'win64')(c);
            const b = new Uint8Array(p.readByteArray(16));
            let s = '';
            for (let i = 0; i < 16; i++) s += ('0' + b[i].toString(16)).slice(-2);
            id = s.toUpperCase();
        } catch (e) {}
        addIds[id] = (addIds[id] || 0) + 1;
        if (!ent.isNull()) {
            const k = ent.toString();
            addByEntity[k] = (addByEntity[k] || 0) + 1;
        }
        if (addCalls <= 60) {
            send('[add] #' + addCalls + ' ent=' + ent + ' id=' + id +
                 ' name=' + (NAMES[id] || '?') + ' from=' + this.returnAddress);
        }
    }
});
// The money shot: when the component lookup FAILS, which type id was asked and
// which ids does the entity actually carry? FUN_1413fb700(entity, id) walks the
// component vector at [entity+0x10]..[entity+0x18] and compares each component's
// vtable[0]() 16-byte id with the asked one. Calling vtable[0] is a read-only
// id getter. Every caller that logs "Couldn't get Transform component" reaches
// this same function, so a null return is exactly the failing lookup.
function idOfPtr(p) {
    try { return p.readU64().toString(16) + ':' + p.add(8).readU64().toString(16); }
    catch (e) { return 'err'; }
}
function componentId(comp) {
    try {
        const vt = comp.readPointer();
        const fn = vt.readPointer();
        const getter = new NativeFunction(fn, 'pointer', ['pointer'], 'win64');
        return idOfPtr(getter(comp));
    } catch (e) { return 'err'; }
}
let lkTotal = 0;
let lkMiss = 0;
let warnPathCalls = 0;
let warnPathMiss = 0;
let playerTransform = null;
let watchArmed = false;
let transformWrites = 0;
const transformWriters = Object.create(null);
const TRANSFORM_WATCH_SIZE = 0x210;
function armTransformWatch() {
    if (!playerTransform || watchArmed) return;
    watchArmed = true;
    try {
        MemoryAccessMonitor.enable(
            { base: playerTransform, size: TRANSFORM_WATCH_SIZE },
            {
                onAccess(details) {
                    if (details.operation !== 'write') return;
                    transformWrites++;
                    const from = details.from.toString();
                    if (!transformWriters[from]) {
                        transformWriters[from] = 0;
                        send('[mv] transform WRITE from ' + from + ' (rva 0x' +
                             details.from.sub(base).toString(16) + ') at +0x' +
                             details.address.sub(playerTransform).toString(16));
                    }
                    transformWriters[from]++;
                }
            }
        );
        send('[mv] watching transform ' + playerTransform + ' for 0x' +
             TRANSFORM_WATCH_SIZE.toString(16) + ' bytes');
    } catch (e) {
        watchArmed = false;
        send('[mv] MemoryAccessMonitor unavailable: ' + e);
    }
}
const lkAsked = Object.create(null);
const lkMissLogged = Object.create(null);
const warnBySlice = Object.create(null);
const WARN_RET_A = base.add(0x1679A61);
const WARN_RET_B = base.add(0x17882D1);
const TRANSFORM_ID = '484ae67dabd04d9cb2c89bb0eec900e0';
function idKey(p) {
    // canonical hex-order form so it can be compared with a known uuid
    try {
        const b = new Uint8Array(p.readByteArray(16));
        let s = '';
        for (let i = 0; i < 16; i++) s += ('0' + b[i].toString(16)).slice(-2);
        return s;
    } catch (e) { return 'err'; }
}
Interceptor.attach(base.add(0x13FB700), {
    onEnter(args) {
        lkTotal++;
        this.k = idOfPtr(args[1]);
        this.kh = idKey(args[1]);
        this.ent = args[0];
        this.from = this.returnAddress;
    },
    onLeave(ret) {
        lkAsked[this.k] = (lkAsked[this.k] || 0) + 1;
        // Grab the local player's transform component before anything else:
        // 'slices/player.dynamicslice' resolves {484AE67D-...} on an entity
        // with 124 components, so the local player DOES have a transform. Watch
        // it to see whether movement ever writes it.
        if (!ret.isNull() && this.kh === TRANSFORM_ID && !playerTransform) {
            const nm = (this.from.equals(WARN_RET_A) ? currentJobName : currentJobBName) || '';
            if (nm.indexOf('slices/player.dynamicslice') !== -1) {
                playerTransform = ret;
                send('[mv] local player transform comp=' + playerTransform + ' slice=' + nm);
                armTransformWatch();
            }
        }
        const isWarnPath = this.from.equals(WARN_RET_A) || this.from.equals(WARN_RET_B);
        if (isWarnPath) {
            warnPathCalls++;
            const slice = this.from.equals(WARN_RET_A) ? currentJobName : currentJobBName;
            const key = (ret.isNull() ? 'MISS ' : 'HIT  ') + slice;
            if (!warnBySlice[key]) {
                let n = -1;
                try {
                    n = this.ent.add(0x18).readPointer().sub(this.ent.add(0x10).readPointer()).toInt32() / 8;
                } catch (e) {}
                warnBySlice[key] = 'comps=' + n + ' id=' + this.kh;
                send('[lk] ' + key + ' comps=' + n + ' id=' + this.kh +
                     ' matchesTransform=' + (this.kh === TRANSFORM_ID));
            }
            if (ret.isNull()) warnPathMiss++;
            return;
        }
        if (!ret.isNull()) return;
        lkMiss++;
        if (lkMissLogged[this.k]) return;
        lkMissLogged[this.k] = 1;
        let n = -1;
        const ids = [];
        try {
            const b = this.ent.add(0x10).readPointer();
            const e = this.ent.add(0x18).readPointer();
            n = e.sub(b).toInt32() / 8;
            for (let i = 0; i < Math.min(n, 14); i++) {
                ids.push(componentId(b.add(i * 8).readPointer()));
            }
        } catch (err) {}
        send('[lk] MISS asked=' + this.k + ' ent=' + this.ent + ' comps=' + n +
             ' from=' + this.from + ' has=' + ids.join(','));
    }
});
// Keep the periodic line small: only the component names that matter for
// movement. The full id map is noise (thousands of audio/UI components).
const INTERESTING = /RigidBody|Physics|Character|Transform|Movement|Input|Player/;
function interestingIds() {
    const out = {};
    for (const id in addIds) {
        const n = NAMES[id];
        if (n && INTERESTING.test(n)) out[n] = addIds[id];
    }
    return out;
}
setInterval(function () {
    send('[probe] totals factory=' + factoryCalls() + ' creator=' + creatorCalls() +
         ' gate=' + gateCalls() + ' cloner=' + clonerCalls() +
         ' lookups=' + lkTotal + ' misses=' + lkMiss +
         ' addCalls=' + addCalls + ' interesting=' + JSON.stringify(interestingIds()) +
         ' warnPathCalls=' + warnPathCalls + ' warnPathMiss=' + warnPathMiss +
         ' playerTransform=' + playerTransform + ' transformWrites=' + transformWrites +
         ' writers=' + JSON.stringify(transformWriters) +
         ' warnSlices=' + JSON.stringify(warnBySlice) +
         ' askedIds=' + JSON.stringify(lkAsked) +
         ' ctxVts=' + JSON.stringify(seenVt));
}, 10000);
send('[eos-stub] transform attach enabled=' + ATTACH_ENABLED);
send('ready');
"""

# The attach branch is a separate experiment: a plain launch only logs.
ATTACH_ENABLED = os.environ.get("AZOTH_TRANSFORM_ATTACH", "0") == "1"
# Only the names that can matter for movement stay in the script: the full
# .rdata table is ~4700 entries (a 340 KB literal) and that made the stub heavy
# to load. The filter keeps the component families a movable character needs.
_NAMES_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "Temp" / "azoth-names.json"
_NAME_FILTER = re.compile(
    r"RigidBody|Physics|Character|Transform|Movement|Locomotion|Input|Player|"
    r"Controller|Actor|Gravity|Collision|Velocity|Traversal|Camera"
)
try:
    _ALL_NAMES = json.loads(_NAMES_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _ALL_NAMES = {}
_NAMES = {k: v for k, v in _ALL_NAMES.items() if _NAME_FILTER.search(v)}
JS = JS.replace("__NAMES__", json.dumps(_NAMES))
JS = JS.replace("__ATTACH_ENABLED__", "true" if ATTACH_ENABLED else "false")


def main() -> int:
    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        print("NewWorld.exe not running")
        return 1
    ready: list[str] = []

    def on_message(message: dict, _data: object) -> None:
        if message.get("type") == "send" and message.get("payload") == "ready":
            ready.append("ok")
        text = message.get("payload")
        if text is None:
            text = message.get("description") or message.get("stack") or message
        _log(f"{message.get('type')} {text}")

    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    for _ in range(20):
        if ready:
            break
        time.sleep(0.1)
    if not ready:
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
