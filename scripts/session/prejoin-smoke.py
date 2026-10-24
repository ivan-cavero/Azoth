"""End-to-end pre-join smoke test through Caddy -> gateway, over the REAL client
hostnames, using Windows Schannel (like the game does).

Why not plain Python TLS: the client uses the Windows certificate store, so a
Git Bash / requests check can report a false failure. PowerShell's
`Invoke-WebRequest` goes through Schannel, which is what the game uses.

This exercises exactly the chain the client walks before it can join a world:
channel config -> CMS metadata -> identity/token/login -> entitlements ->
world list. It is the same gate the runbook says to clear before launching, so a
green run here means "the HTTP side is ready; only the client is left".

Usage:  python scripts/prejoin-smoke.py
Exit 0 = every reachable endpoint answered as expected.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (label, host, path, expected status).
# Paths are the ones the client was actually observed requesting
# (research/atlas/observed-endpoints.json), not guesses: a guessed path 404s and
# would look like a gateway defect.
CHECKS: list[tuple[str, str, str, int]] = [
    ("channel-config", "d2c74t4zimux3r.cloudfront.net",
     "/STEAM_APP_ID.json", 200),
    ("cms-news", "d1hkbwzm1bktgo.cloudfront.net",
     "/newsstories/STEAM_APP_ID/metadata.json", 200),
    ("cms-tiles", "d1hkbwzm1bktgo.cloudfront.net",
     "/marketingtiles/STEAM_APP_ID/metadata.json", 200),
    ("cms-motd", "d1hkbwzm1bktgo.cloudfront.net",
     "/motd/worlds_STEAM_APP_ID.json", 200),
    ("cms-configset-productid", "d1hkbwzm1bktgo.cloudfront.net",
     "/applications/publicGameplay/configuration-sets/ProductId/STEAM_APP_ID/versionless", 200),
    ("cms-configset-worldid", "d1hkbwzm1bktgo.cloudfront.net",
     "/applications/publicGameplay/configuration-sets/WorldId/x/versionless", 200),
    ("login-gateway", "u433g9r00c.execute-api.eu-central-1.amazonaws.com",
     "/prod/game/getlogininfo/jwt/omni", 200),
    ("login-queue", "u433g9r00c.execute-api.eu-central-1.amazonaws.com",
     "/prod/game/login/queue/v2/enqueue", 200),
    ("javelin-gateway", "8otrnl8e8d.execute-api.eu-central-1.amazonaws.com",
     "/prod/game/worlds/list/jwt/omni", 200),
    ("entitlements", "client.entitlementservice.amazongames.com",
     "/players/amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c/games/new-world/platforms/steam/entitlements", 200),
    ("omni-tokens", "tokenservice.amazongames.com",
     "/prod/credentials/omni", 200),
    ("identity", "prod.identity-service.amazongames.com",
     "/auth/platform/user/code", 200),
]

# Endpoints on the gateway's own health surface. `/live.json` is deliberately NOT
# here: it is a landing-site asset (site/public/live.json), not a gateway route, so
# checking it against the gateway host is a wrong test, not a gateway defect.
HEALTH_CHECKS: list[tuple[str, str, str, int]] = [
    ("gw-healthz", "d1w0bfy6smo4d1.cloudfront.net", "/healthz", 200),
    ("gw-ping", "d1w0bfy6smo4d1.cloudfront.net", "/ping", 200),
]

PS = "powershell.exe"


def probe(host: str, path: str) -> tuple[int | None, str]:
    """Return (status, detail) for one URL via Schannel."""
    url = f"https://{host}{path}"
    script = (
        f"try {{ $r = Invoke-WebRequest -UseBasicParsing -Uri '{url}' "
        f"-TimeoutSec 12; "
        f"Write-Output ('STATUS ' + $r.StatusCode); "
        f"Write-Output ('ETAG ' + $r.Headers['ETag']) "
        f"}} catch {{ "
        f"$c = $_.Exception.Response.StatusCode.value__; "
        f"if ($c) {{ Write-Output ('STATUS ' + $c) }} "
        f"else {{ Write-Output ('STATUS 0'); Write-Output ('ERR ' + $_.Exception.Message) }} "
        f"}}"
    )
    try:
        out = subprocess.run(
            [PS, "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=40,
        ).stdout
    except subprocess.TimeoutExpired:
        return None, "timeout"
    status = None
    extra = []
    for line in out.splitlines():
        if line.startswith("STATUS "):
            status = int(line.split()[1])
        elif line.startswith("ETAG "):
            extra.append(line.strip())
        elif line.startswith("ERR "):
            extra.append(line.strip())
    return status, "; ".join(extra)


def run(checks: list[tuple[str, str, str, int]], failures: list[str]) -> None:
    for label, host, path, want in checks:
        status, detail = probe(host, path)
        ok = status == want
        if not ok:
            failures.append(f"{label}: got {status}, want {want} ({detail})")
        print(f"{label:<26} {str(status):>6}  {'ok' if ok else 'FAIL'} {detail}")


def main() -> int:
    failures: list[str] = []
    print(f"{'check':<26} {'status':>6}  detail")
    run(HEALTH_CHECKS, failures)
    run(CHECKS, failures)
    # ETag is mandatory for the CMS docs: the client crashes without it.
    status, detail = probe("d1hkbwzm1bktgo.cloudfront.net",
                           "/newsstories/STEAM_APP_ID/metadata.json")
    if "ETAG" not in detail or detail.rstrip().endswith("ETAG"):
        failures.append("cms news metadata.json is missing an ETag header")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nall pre-join endpoints answered as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
