# Refreshes site/public/live.json.
#
# Two modes:
#   default        — local machine: reads .azoth/state/*.json pids and checks
#                    them with tasklist (Windows). This is what `az.py dev`
#                    calls.
#   --ci           — GitHub Actions: there is no stack; publish an honest
#                    "agent idle" snapshot instead of fake data.

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
STATE = ROOT / ".azoth" / "state"
OUT = ROOT / "site" / "public" / "live.json"
SERVICES = ("caddy", "gateway", "world")


def pid_alive(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def main() -> int:
    live = {
        "agentRunning": False,
        "lastHeartbeat": None,
        "services": {name: False for name in SERVICES},
        "mode": "local",
    }

    if "--ci" in sys.argv:
        live["mode"] = "ci"
    else:
        for name in SERVICES:
            state_file = STATE / f"{name}.json"
            if not state_file.exists():
                continue
            try:
                pid = json.loads(state_file.read_text(encoding="utf-8")).get("pid")
                if pid and pid_alive(int(pid)):
                    live["services"][name] = True
            except Exception:
                continue
        live["agentRunning"] = any(live["services"].values())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} (mode {live['mode']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
