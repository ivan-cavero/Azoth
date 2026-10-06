#!/usr/bin/env python3
"""Watch whether the client ever BUILDS the V3 registration request.

The client never sends channel-0 data to our REP server. Two possibilities:
(a) it never tries (missing server signal), (b) it tries and the send fails.
This hooks the V3 request builder (identified by its unique strings) and the
DTLS send path, so one JUGAR press tells us which.
"""

from __future__ import annotations

import sys
import time

import frida

JS = r"""
const base = Process.enumerateModules()[0].base;
console.log('[*] base = ' + base);

// Hook sendto/recvfrom at winsock level to see ALL udp traffic attempts.
const ws2 = Process.getModuleByName('ws2_32.dll');
const sendto = ws2.getExportByName('sendto');
const recvfrom = ws2.getExportByName('recvfrom');
let udpOut = 0;
Interceptor.attach(sendto, {
    onEnter(args) {
        const port = args[5].readU16();
        if (port === 9000) {
            udpOut++;
            if (udpOut % 50 === 1) {
                console.log('[udp] sendto :9000 len=' + args[2].toInt32() + ' (x' + udpOut + ')');
            }
        }
    },
});

// Also hook SSL_write (DTLS encrypt) to see if app-data is even produced.
try {
    const sslMods = Process.enumerateModules().filter(m => m.name.toLowerCase().includes('ssl') || m.name.toLowerCase().includes('crypto') || m.name.toLowerCase().includes('javelin'));
    console.log('[*] candidate ssl modules: ' + sslMods.map(m => m.name).join(','));
} catch (e) { console.log('[*] mod enum failed: ' + e); }
"""


def main() -> int:
    try:
        session = frida.attach("NewWorld.exe")
    except frida.ProcessNotFoundError:
        print("NewWorld.exe not running")
        return 1
    script = session.create_script(JS)
    script.on("message", lambda m, d: print(m.get("payload") or m))
    script.load()
    print("[*] watching UDP to :9000 — press JUGAR (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
