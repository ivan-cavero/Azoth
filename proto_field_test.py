
import json
import time

import frida

GINFO = r'C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\emulator\apps\gateway\mock_discovery\getlogininfo.json'
b64s_by_field = json.load(open(r'C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\jwt_proto_b64_by_field.json'))

FRIDA_JS = r"""
var base = Process.getModuleByName('NewWorld.exe').base;
Interceptor.attach(base.add(0x6429770), { onEnter: function(args){ this.inp = args[1]; },
  onLeave: function(ret){
    var lo = this.inp.readS64(), hi = this.inp.add(8).readS64();
    var cnt = Number((hi - lo) / 0x1b0);
    send({tag:'count', n: cnt});
}});
"""

def measure():
    try:
        session = frida.attach("NewWorld.exe")
        script = session.create_script(FRIDA_JS)
        got = []
        script.on('message', lambda m,d: got.append(m.get('payload',{}).get('n',-1)) if m['type']=='send' else None)
        script.load()
        t0 = time.time()
        while time.time()-t0 < 80:
            time.sleep(5)
        session.detach()
        return max(got) if got else None
    except Exception as e:
        print('frida err', e, flush=True)
        return None

token = json.load(open(GINFO))
results = open(r'C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\proto-field-results.log','a')
for wf, b64s in b64s_by_field.items():
    token['JwtClaims'] = b64s
    json.dump(token, open(GINFO,'w'), indent=1)
    print(f'--- worlds_field={wf} served ---', flush=True)
    time.sleep(75)  # esperar el poll del cliente (60s)
    cnt = measure()
    line = f'worlds_field={wf} -> count={cnt}'
    print(line, flush=True)
    results.write(line+'\n'); results.flush()
    if cnt and cnt > 0:
        print('*** WORLDS DETECTADOS ***', flush=True)
        break
results.close()
print('done')
