// Hook the JSON deserializer member lookups in NewWorld.exe.
// FUN_147465730 = HasMember(json, name)  RVA 0x7465730
// FUN_147465440 = Get<T>(json, name)     RVA 0x7465440
// FUN_146456b60 = UI world-list converter (result + 0x18 = count)  RVA 0x64656b60
// FUN_1464585d0 = second converter                                  RVA 0x646585d0

const base = Process.getModuleByName("NewWorld.exe").base;

function readName(p) {
    try {
        const s = p.readUtf8String(64);
        return s ? s.slice(0, 48) : "(?)";
    } catch {
        return "(unreadable)";
    }
}

function hookRva(rva, label, onEnter) {
    try {
        Interceptor.attach(base.add(rva), { onEnter });
        console.log(`hooked ${label} @${rva.toString(16)}`);
    } catch (e) {
        console.log(`hook-err ${label} ${e}`);
    }
}

const now = () => Date.now() % 100000;

hookRva(0x7465730, "HasMember", (args) => {
    console.log(`${now()} MEMBER ${readName(args[1])}`);
});

hookRva(0x7465440, "Get", (args) => {
    console.log(`${now()} GET ${readName(args[1])}`);
});

hookRva(0x64656b60, "convA(count@r+0x18)", (args) => {
    try {
        const cnt = args[1].add(0x18).readS32();
        console.log(`${now()} CONVA count=${cnt}`);
    } catch (e) {
        console.log(`${now()} CONVA read-err`);
    }
});

hookRva(0x646585d0, "convB(count@r+0x40)", (args) => {
    try {
        const cnt = args[1].add(0x40).readS32();
        console.log(`${now()} CONVB count=${cnt}`);
    } catch (e) {
        console.log(`${now()} CONVB read-err`);
    }
});

console.log(`${now()} ready`);
