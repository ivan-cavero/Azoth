import base64
import json
import subprocess
import time

import frida

LAUNCHER = (
  r"C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\launcher\src\Start-NwPrivate.ps1"
)
GINFO = r"C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\emulator\apps\gateway\mock_discovery\getlogininfo.json"
RESULTS = r"C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\jwt-combo-results.log"


def b64(d):
  return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def write_body(root_claim, pop_val):
  now = int(time.time())
  world = {
    "worldId": "00000000-0000-4000-8000-000000000001",
    "id": "00000000-0000-4000-8000-000000000001",
    "name": "azoth-1-01",
    "type": "OpenWorld",
    "worldType": "OpenWorld",
    "status": "ACTIVE",
    "publicStatusCode": 0,
    "publicName": "Azoth-1",
    "version": "1.400.6031.6004151",
    "maxAccountCharacters": 4,
    "worldSet": "azoth-1",
    "worldMetrics": {
      "worldPopulationStatus": pop_val,
      "worldAgeDays": 1,
      "queueSize": 0,
      "queueWaitTimeSec": 0,
    },
    "transferToRegion": "",
    "isFull": False,
    "isRecommended": True,
    "regionId": "azoth-1",
  }
  inner = {
    "sub": "00000000-0000-4000-8000-000000000001",
    root_claim: [world],
    "recommendedWorlds": [],
    "pendingWorldMerges": [],
    "LoginInfoList": [dict(world, characters=[])],
  }
  inner_jwt = b64({"alg": "none", "typ": "JWT"}) + "." + b64(inner) + "."
  token = {
    "PersonaId": "amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c",
    "CharacterId": "",
    "ChannelId": "azoth-1",
    "IsTrialOwner": False,
    "AccountAge": 365,
    "AccountIsLocked": False,
    "RepAddress": "127.0.0.1:9000",
    "GenerateTime": now,
    "IssueTime": now,
    "TokenVersion": 1,
    "JwtClaims": inner_jwt,
  }
  json.dump(token, open(GINFO, "w"), indent=1)


def restart_game():
  subprocess.run(["taskkill", "/IM", "NewWorld.exe", "/F"], capture_output=True)
  time.sleep(3)
  subprocess.run(
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", LAUNCHER],
    capture_output=True,
  )
  time.sleep(95)
  subprocess.run(
    [
      "orca",
      "computer",
      "press-key",
      "--app",
      "NewWorld",
      "--key",
      "Return",
      "--restore-window",
      "--json",
    ],
    capture_output=True,
  )
  time.sleep(45)


FRIDA_JS = r"""
var base = Process.getModuleByName('NewWorld.exe').base;
Interceptor.attach(base.add(0x6429770), { onEnter: function(args){ this.inp = args[1]; },
  onLeave: function(ret){
    var lo = this.inp.readS64(), hi = this.inp.add(8).readS64();
    var cnt = Number((hi - lo) / 0x1b0);
    send({tag:'count', n: cnt});
}});
"""


def measure_count():
  try:
    session = frida.attach("NewWorld.exe")
    script = session.create_script(FRIDA_JS)
    got = []
    script.on(
      "message",
      lambda m, d: (
        got.append(m.get("payload", {}).get("n", -1)) if m["type"] == "send" else None
      ),
    )
    script.load()
    t0 = time.time()
    while time.time() - t0 < 75:
      time.sleep(5)
    session.detach()
    return max(got) if got else None
  except Exception as e:
    print("frida err", e, flush=True)
    return None


combos = []
for rc in ("Worlds", "worlds", "LoginInfoList"):
  for pop in ("LOW", 0):
    combos.append((rc, pop))

results = open(RESULTS, "a")
for root_claim, pop in combos:
  print(f"=== combo: root={root_claim} pop={pop!r} ===", flush=True)
  write_body(root_claim, pop)
  restart_game()
  cnt = measure_count()
  line = f"root={root_claim} pop={pop!r} -> worlds_count={cnt}"
  print(line, flush=True)
  results.write(line + "\n")
  results.flush()
  if cnt and cnt > 0:
    print("!!! WORLDS LLENADO !!!", flush=True)
    break
results.close()
print("loop finished")
