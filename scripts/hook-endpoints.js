// Hook connection + HTTP endpoints of NewWorld.exe (Frida 17 API).

function ts() {
    return Date.now() % 100000;
}

function exp(mod, fn) {
    try {
        return Process.getModuleByName(mod).getExportByName(fn);
    } catch {
        console.log(`no-export ${mod}.${fn}`);
        return null;
    }
}

function sockaddr(family, buf) {
    if (family === 2) {
        const port = buf.getU16(2);
        const ip = Array.from(buf.add(4).readByteArray(4)).join(".");
        return `${ip}:${port}`;
    }
    if (family === 23) {
        const port = buf.getU16(2);
        const b = buf.add(8).readByteArray(16);
        const parts = [];
        for (let i = 0; i < 16; i += 2)
            parts.push(((b[i] << 8) | b[i + 1]).toString(16));
        return `[${parts.join(":")}]:${port}`;
    }
    return `fam=${family}`;
}

for (const fn of ["connect", "WSAConnect"]) {
    const p = exp("ws2_32.dll", fn);
    if (!p) continue;
    Interceptor.attach(p, {
        onEnter(args) {
            this.tgt = sockaddr(args[1].readU16(0), args[1]);
        },
        onLeave(ret) {
            console.log(`${ts()} CONNECT ${fn} -> ${this.tgt} ret=${ret}`);
        },
    });
    console.log(`hooked ${fn}`);
}

for (const fn of ["WinHttpConnect", "WinHttpOpenRequest"]) {
    const p = exp("winhttp.dll", fn);
    if (!p) continue;
    Interceptor.attach(p, {
        onEnter(args) {
            if (fn === "WinHttpConnect") {
                const host = args[1].isNull() ? "?" : args[1].readUtf16String();
                this.info = `server=${host}:${args[2]}`;
            } else {
                const verb = args[1].isNull() ? "?" : args[1].readUtf16String();
                const path = args[2].isNull() ? "?" : args[2].readUtf16String();
                this.info = `${this.info || ""} | ${verb} ${path}`;
            }
        },
        onLeave() {
            if (this.info) console.log(`${ts()} HTTP ${this.info}`);
        },
    });
    console.log(`hooked winhttp.${fn}`);
}

console.log(`${ts()} ready`);
