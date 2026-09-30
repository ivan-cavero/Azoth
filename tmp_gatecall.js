
const mod = Process.findModuleByName("NewWorld.exe");
const base = mod.base;
const at = (va) => base.add(va - 0x140000000);
let n = 0;
const callers = {};
Interceptor.attach(at(0x146800d10), {
  onEnter: function(args) {
    n++;
    if (n % 5000 === 0) {
      const ra = this.returnAddress.toString();
      callers[ra] = (callers[ra]||0)+1;
    }
    if (n % 50000 === 0) send({ev:'tick', n:n, callers:callers});
  }
});
send({ev: 'ready'});
