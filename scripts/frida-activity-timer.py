#!/usr/bin/env python3
"""Find who seals the client's network activity stamp (the red-cable timer).

The debug HUD prints `Time since last response = FUN_141413890() - *(obj+0xAA8)`
(FUN_14487b300, shard-000990.c:8110) and the warning-state updater FUN_14486c740
(shard-000991.c:14461) does the same and sets state 2 once the gap exceeds the
runtime global _DAT_149f21054. Nothing in the corpus writes +0xAA8 on that
object, so the writer is found at runtime instead: hook FUN_14486c740 to grab
the object, then watch [obj+0xAA8, obj+0xB00) and report the writing instruction.

Read-only. No attach, no packet injection.

Usage: python scripts/frida-activity-timer.py [seconds]
"""

from __future__ import annotations

import sys
import time

import frida

STAMP_RVA = 0x486C740  # FUN_14486c740, the warning-state updater
TIMER_OFF = 0xAA8
THRESHOLD_VA = 0x149F21054

JS = r"""
const mod = Process.findModuleByName('NewWorld.exe');
if (!mod) { throw new Error('no NewWorld.exe'); }
const base = mod.base;
send('[timer] base ' + base);

let obj = null;
let armed = false;
let rearmBudget = 400;
let seen = 0;
let writes = 0;
let thresholdLogged = false;
const writers = Object.create(null);

function readStamp(o) {
    try { return o.add(0xAA8).readU64().toString(); } catch (e) { return 'err'; }
}

function arm() {
    if (!obj || armed || rearmBudget <= 0) return;
    armed = true;
    try {
        MemoryAccessMonitor.enable({ base: obj.add(0xAA8), size: 8 }, {
            onAccess(details) {
                armed = false;
                seen++;
                try { MemoryAccessMonitor.disable(); } catch (e) {}
                const from = details.from.toString();
                if (details.operation === 'write') {
                    writes++;
                    if (!writers[from]) {
                        writers[from] = 0;
                        let value = 'err';
                        try { value = details.address.readU64().toString(); } catch (e) {}
                        send('[timer] WRITER ' + details.from + ' (rva 0x' +
                             details.from.sub(base).toString(16) + ') value=' + value);
                    }
                    writers[from]++;
                } else if (seen <= 6) {
                    send('[timer] access op=' + details.operation + ' from ' + from);
                }
                rearmBudget--;
                if (rearmBudget <= 0) {
                    send('[timer] done: accesses=' + seen + ' writes=' + writes +
                         ' distinctWriters=' + Object.keys(writers).length);
                    return;
                }
                setTimeout(arm, 0);
            }
        });
    } catch (e) {
        armed = false;
        send('[timer] monitor failed: ' + e);
    }
}

Interceptor.attach(base.add(0x486C740), {
    onEnter(args) {
        if (obj === null && !args[0].isNull()) {
            obj = args[0];
            send('[timer] object from warning-updater ' + obj + ' stamp=' + readStamp(obj));
            arm();
        }
    }
});

// The debug HUD reads the same +0xAA8 on the same object and runs every frame
// while it is visible, so it is the reliable way to obtain the pointer.
let hudCalls = 0;
Interceptor.attach(base.add(0x487B300), {
    onEnter(args) {
        hudCalls++;
        if (hudCalls === 1) send('[timer] hud calls started');
        if (obj === null && !args[0].isNull()) {
            obj = args[0];
            send('[timer] object from HUD ' + obj + ' stamp=' + readStamp(obj));
            arm();
        }
        if (obj !== null && !thresholdLogged) {
            thresholdLogged = true;
            try {
                const t = base.add(0x9F21054).readU64().toString();
                send('[timer] threshold=' + t + ' stamp=' + readStamp(obj) +
                     ' nowMs=' + Date.now());
            } catch (e) {
                send('[timer] threshold unreadable: ' + e);
            }
        }
    }
});

let polls = 0;
setInterval(function () {
    if (obj === null || polls >= 12) return;
    polls++;
    send('[timer] poll stamp=' + readStamp(obj) + ' seen=' + seen + ' writes=' + writes);
}, 5000);
send('ready');
"""


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
    session = frida.attach("NewWorld.exe")
    ready: list[str] = []

    def on_message(message: dict, _data: object) -> None:
        payload = message.get("payload")
        if payload == "ready":
            ready.append("ok")
        stamp = time.strftime("%H:%M:%S")
        text = payload
        if text is None:
            text = message.get("description") or message
        print(f"{stamp} {message.get('type')} {text}", flush=True)

    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    for _ in range(30):
        if ready:
            break
        time.sleep(0.1)
    if not ready:
        print("script did not signal ready")
        return 1
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
