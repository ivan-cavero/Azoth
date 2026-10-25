#!/usr/bin/env python3
"""Trust Caddy's current local CA so the private client can reach the gateway.

Why this exists (measured 2026-10-07): Caddy terminates TLS for every
redirected host with its own local issuing authority. A fresh
`.azoth/caddy/data/` makes Caddy generate a NEW root with the same subject
(`CN=Caddy Local Authority - 2026 ECC Root`) but a different key, while
Windows still trusts an older one. Same name, different thumbprint, no error
anywhere: the client hangs at the title gate and the gateway logs zero
requests. See research/docs/PRIVATE-CLIENT-RUNBOOK.md, gate 2.

The game validates TLS through Schannel (the Windows store), so importing the
root into `Cert:\\CurrentUser\\Root` is enough; no admin and no LocalMachine
write is required.

Usage:
  python scripts/trust-caddy-ca.py           # import current, drop stale
  python scripts/trust-caddy-ca.py --check    # read-only, exit 1 on drift
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CADDY_ROOT = ROOT / ".azoth" / "caddy" / "data" / "caddy" / "pki" / "authorities" / "local" / "root.crt"

PS = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]

# Read-only: report the on-disk thumbprint and every trusted Caddy root.
_CHECK = r"""
$root = '{root}'
if (-not (Test-Path -LiteralPath $root)) {{ Write-Output 'NO_ROOT_FILE'; exit 2 }}
$disk = (Get-PfxCertificate -FilePath $root).Thumbprint
Write-Output ("disk=" + $disk)
$trusted = @(Get-ChildItem Cert:\CurrentUser\Root | Where-Object {{ $_.Subject -like '*Caddy Local Authority*' }})
if ($trusted.Count -eq 0) {{ Write-Output 'trusted=<none>'; Write-Output 'drift=missing'; exit 1 }}
foreach ($c in $trusted) {{ Write-Output ("trusted=" + $c.Thumbprint) }}
if ($trusted.Thumbprint -contains $disk) {{ Write-Output 'drift=ok'; exit 0 }}
Write-Output 'drift=stale'
exit 1
"""

# Import current, remove every Caddy root that is not the current one.
_APPLY = r"""
$root = '{root}'
if (-not (Test-Path -LiteralPath $root)) {{ Write-Output 'NO_ROOT_FILE'; exit 2 }}
$disk = (Get-PfxCertificate -FilePath $root).Thumbprint
Get-ChildItem Cert:\CurrentUser\Root |
    Where-Object {{ $_.Subject -like '*Caddy Local Authority*' -and $_.Thumbprint -ne $disk }} |
    ForEach-Object {{ Write-Output ('removed ' + $_.Thumbprint); Remove-Item -LiteralPath $_.PSPath -Force }}
$have = Get-ChildItem Cert:\CurrentUser\Root |
    Where-Object {{ $_.Subject -like '*Caddy Local Authority*' -and $_.Thumbprint -eq $disk }}
if (-not $have) {{
    $new = Import-Certificate -FilePath $root -CertStoreLocation Cert:\CurrentUser\Root
    Write-Output ('imported ' + $new.Thumbprint)
}} else {{
    Write-Output ('already trusted ' + $disk)
}}
exit 0
"""


def run(script: str) -> int:
    if not CADDY_ROOT.is_file():
        print(f"caddy root not found: {CADDY_ROOT}")
        print("start the stack once (`python ef.py dev`) so Caddy creates its PKI.")
        return 2
    result = subprocess.run(
        [*PS, "-Command", script.format(root=str(CADDY_ROOT))],
        cwd=ROOT,
        text=True,
    )
    return result.returncode


def main() -> int:
    check = "--check" in sys.argv
    code = run(_CHECK if check else _APPLY)
    if check and code == 0:
        print("caddy CA trust: ok")
    elif check:
        print("caddy CA trust: drift — run `python scripts/trust-caddy-ca.py`")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
