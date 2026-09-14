#requires -Version 5.1
<#
.SYNOPSIS
  Switch Azoth network profile: private (Azoth gateway) or official (Amazon).
.DESCRIPTION
  private:   appends 127.0.0.1/::1 entries for the hosts in
             deploy/hosts-allowlist.json "redirect" list (needs admin).
  official:  removes the Azoth block, restores vanilla online play.
  The block is delimited by markers so official mode is a clean removal.
  Safety: refuses to write if the surviving content looks empty (keeps a
  timestamped backup either way). Uses Write-Output so callers can capture
  logs with redirection (Write-Host is NOT capturable).
.EXAMPLE
  powershell -File deploy\switch-mode.ps1 private    # UAC prompt, needs admin
  powershell -File deploy\switch-mode.ps1 official
  powershell -File deploy\switch-mode.ps1 status     # read-only drift check, no admin
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('private', 'official', 'status')]
    [string]$Mode,
    [string]$HostsPath = "$env:SystemRoot\System32\drivers\etc\hosts",
    [string]$AllowlistPath = '',
    [switch]$SkipElevationCheck
)

$ErrorActionPreference = 'Stop'

# NOTE: do not default AllowlistPath from $PSScriptRoot in param(): it is
# empty under some hosts (-Command, constrained sessions). Resolve here.
if ([string]::IsNullOrWhiteSpace($AllowlistPath)) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    if ([string]::IsNullOrWhiteSpace($here)) { $here = $PSScriptRoot }
    if ([string]::IsNullOrWhiteSpace($here)) { throw 'cannot locate deploy dir for hosts-allowlist.json' }
    $AllowlistPath = Join-Path $here 'hosts-allowlist.json'
}

function Test-Elevated {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $SkipElevationCheck -and $Mode -ne 'status' -and -not (Test-Elevated)) {
    throw 'switch-mode needs admin (right-click PowerShell > Run as administrator)'
}

$beginMark = '# >>> AZOTH PRIVATE >>>'
$endMark = '# <<< AZOTH PRIVATE <<<'

$allow = Get-Content -LiteralPath $AllowlistPath -Raw | ConvertFrom-Json
$raw = Get-Content -LiteralPath $HostsPath -ErrorAction Stop
if ($null -eq $raw) { throw "refusing: could not read $HostsPath" }
$hosts = @($raw)

# Strip any previous Azoth block.
$clean = @()
$inside = $false
foreach ($line in $hosts) {
    if ($line -eq $beginMark) { $inside = $true; continue }
    if ($line -eq $endMark) { $inside = $false; continue }
    if (-not $inside) { $clean += $line }
}

# Read-only drift check: compare the allowlist against the live block.
# Exits 1 when the block is missing or stale (CI-friendly), 0 when in sync.
if ($Mode -eq 'status') {
    $have = @{}
    $inBlock = $false
    foreach ($line in $hosts) {
        if ($line -eq $beginMark) { $inBlock = $true; continue }
        if ($line -eq $endMark) { $inBlock = $false; continue }
        if ($inBlock -and $line -match '^\s*(127\.0\.0\.1|::1)\s+(\S+)') {
            $have[$Matches[2]] = $true
        }
    }
    $want = @($allow.redirect | ForEach-Object { $_.host })
    $missing = @($want | Where-Object { -not $have.ContainsKey($_) })
    $stale = @($have.Keys | Where-Object { $_ -notin $want })
    Write-Output "mode=status allowlist=$($want.Count) blocked=$($have.Count)"
    if ($missing.Count -gt 0) {
        Write-Output "missing: $($missing -join ', ')"
    }
    if ($stale.Count -gt 0) {
        Write-Output "stale: $($stale -join ', ')"
    }
    if ($missing.Count -eq 0 -and $stale.Count -eq 0) {
        Write-Output 'in-sync'
        exit 0
    }
    Write-Output 'drift: run switch-mode.ps1 private'
    exit 1
}

if ($clean.Count -lt 3) { throw "refusing: surviving hosts content suspiciously small ($($clean.Count) lines)" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$HostsPath.azoth-bak-$stamp"
Copy-Item -LiteralPath $HostsPath -Destination $backup -Force
Write-Output "backup: $backup"

if ($Mode -eq 'official') {
    $new = $clean
    Write-Output 'official: Azoth block removed'
} else {
    $block = @($beginMark)
    foreach ($entry in $allow.redirect) {
        $block += "127.0.0.1`t$($entry.host)"
        # ::1 is NOT optional: the client opens AF_INET6 sockets, so an AAAA
        # lookup that returns the real CloudFront IPv6 bypasses the 127.0.0.1
        # line entirely (first-light Frida traces 2026-04-26).
        $block += "::1`t$($entry.host)"
    }
    $block += $endMark
    $new = $clean + $block
    Write-Output "private: $($allow.redirect.Count) hosts redirected to loopback"
}

$tmp = "$HostsPath.azoth-tmp"
Set-Content -LiteralPath $tmp -Value $new -Encoding ascii -ErrorAction Stop
Move-Item -LiteralPath $tmp -Destination $HostsPath -Force -ErrorAction Stop
Write-Output "wrote $HostsPath ($($new.Count) lines)"

ipconfig /flushdns | Out-Null
Write-Output 'dns cache flushed'
