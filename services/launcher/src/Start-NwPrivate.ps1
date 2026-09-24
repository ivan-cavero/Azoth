#requires -Version 5.1
# Launch New World WITHOUT Steam and WITHOUT EAC.
# Uses an Azoth steam_api64 stub in a private runtime dir. Never overwrites the Steam install.
[CmdletBinding()]
param(
    [string]$InstallRoot = "C:\Program Files (x86)\Steam\steamapps\common\New World",
    [string]$RuntimeRoot = $(Join-Path $env:LOCALAPPDATA 'Azoth\game'),
    [switch]$Watch
)

$ErrorActionPreference = 'Stop'
$SteamAppId = '1063730'
$repoLauncher = Split-Path -Parent $PSScriptRoot
$stubDll = Join-Path $repoLauncher 'steam_stub\steam_api64.dll'
$stubBuild = Join-Path $repoLauncher 'steam_stub\build.ps1'

if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot 'Bin64\NewWorld.exe'))) {
    throw "Game install not found: $InstallRoot"
}

if (-not (Test-Path -LiteralPath $stubDll)) {
    Write-Host "Building steam_api64 stub (no Steam)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stubBuild
    if (-not (Test-Path -LiteralPath $stubDll)) { throw "Stub DLL missing: $stubDll" }
}

$rtBin = Join-Path $RuntimeRoot 'Bin64'
New-Item -ItemType Directory -Force -Path $rtBin | Out-Null

function Link-File([string]$Src, [string]$Dst) {
    if (Test-Path -LiteralPath $Dst) { return }
    try {
        New-Item -ItemType HardLink -Path $Dst -Target $Src | Out-Null
    } catch {
        Copy-Item -LiteralPath $Src -Destination $Dst -Force
    }
}

# Game root: junction assets + hardlink small configs. Do not copy PAKs.
$assetsSrc = Join-Path $InstallRoot 'assets'
$assetsDst = Join-Path $RuntimeRoot 'assets'
if (-not (Test-Path -LiteralPath $assetsDst)) {
    try {
        New-Item -ItemType Junction -Path $assetsDst -Target $assetsSrc | Out-Null
    } catch {
        cmd /c "mklink /J `"$assetsDst`" `"$assetsSrc`"" | Out-Null
    }
}
foreach ($name in @('bootstrap.cfg', 'engine.json', 'PaksList.lst', 'system_windows_pc.cfg', 'typeindex.json')) {
    $src = Join-Path $InstallRoot $name
    if (Test-Path -LiteralPath $src) {
        Link-File $src (Join-Path $RuntimeRoot $name)
    }
}

# Bin64: hardlink every file except Steam/EAC, then drop our stub.
Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'Bin64') -File | ForEach-Object {
    if ($_.Name -eq 'steam_api64.dll') { return }
    if ($_.Name -like '*.eac') { return }
    Link-File $_.FullName (Join-Path $rtBin $_.Name)
}
Copy-Item -LiteralPath $stubDll -Destination (Join-Path $rtBin 'steam_api64.dll') -Force
Set-Content -LiteralPath (Join-Path $rtBin 'steam_appid.txt') -Value $SteamAppId -Encoding ascii -NoNewline
Set-Content -LiteralPath (Join-Path $RuntimeRoot 'steam_appid.txt') -Value $SteamAppId -Encoding ascii -NoNewline

$exe = Join-Path $rtBin 'NewWorld.exe'
Write-Host "AZOTH PRIVATE LAUNCH (no Steam, no EAC)"
Write-Host "  exe:     $exe"
Write-Host "  stub:    $rtBin\steam_api64.dll"
Write-Host "  assets:  $assetsDst  (junction to install)"
Write-Host "  Steam process is NOT required."

# Official EOS "null anticheat client" switch (Epic integration checklist):
# start the exe directly with this set so ClientSDK does not require EAC.
$env:EOS_USE_ANTICHEATCLIENTNULL = '1'
$p = Start-Process -FilePath $exe -WorkingDirectory $rtBin -ArgumentList '+lc_listWorlds' -PassThru
Write-Host "  pid=$($p.Id)  started $(Get-Date -Format o)"
Write-Host "  Watch Game.log. Green: Channel service uri, no EasyAntiCheat_EOS.exe."

if ($Watch) {
    $repo = Split-Path -Parent (Split-Path -Parent $repoLauncher)
    Write-Host '  Waiting for NewWorld.exe to map, then applying Frida patches...'
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        try {
            $proc = Get-Process -Id $p.Id -ErrorAction Stop
            if ($proc.WorkingSet64 -gt 50MB) { $ready = $true; break }
        } catch {
            Write-Host '  NewWorld.exe exited before patches'
            exit 1
        }
    }
    if (-not $ready) {
        Write-Host '  NewWorld.exe still mapping after 120s - attaching anyway'
    }
    Write-Host '  DTLS verify bypass...'
    & python -u (Join-Path $repo 'scripts\frida-trust-patch.py')
    if ($LASTEXITCODE -ne 0) { Write-Host '  trust-patch FAILED' }
    Write-Host '  Anticheat gate byte-patch...'
    & python -u (Join-Path $repo 'scripts\frida-anticheat-patch.py')
    if ($LASTEXITCODE -ne 0) { Write-Host '  anticheat-patch FAILED' }
    if ($env:AZOTH_NATURAL_SPAWN -eq '1') {
        Write-Host '  Natural spawn ladder enabled (state patches skipped)'
    } else {
        Write-Host '  Force actor/spawn ladder (skip 2min timeout)...'
        & python -u (Join-Path $repo 'scripts\frida-rep-force-ladder.py')
        if ($LASTEXITCODE -ne 0) { Write-Host '  ladder-force FAILED' }
        # v1 (patching the getter BODY 0x146800d10 -> mov eax,1;ret) CRASHED the
        # client (c0000005 @ NewWorld+0x104285d). v2 NOPs the FSM call-site
        # check instead (0x14644a8ed, 9B: test rax,rax + je) — VERIFIED
        # 2026-09-19 19:09: client reached InGame for the first time ever.
        Write-Host '  Force 4th spawn gate (13->14 call-site NOP)...'
        & python -u (Join-Path $repo 'scripts\patch-spawn-gate.py')
        if ($LASTEXITCODE -ne 0) { Write-Host '  spawn-gate-force FAILED' }
    }
    Write-Host '  EOS ClientSDK stubs (window must stay open)...'
    # MUST be a detached, persistent process: the stub holds live Frida
    # NativeCallbacks, and it silently dying = @mm_csdkerr_disconnect (2)
    # 3.5s into InGame (2026-09-20: watchdog launched it via & which
    # returned immediately; stub died with the launcher window).
    Start-Process -WindowStyle Hidden -FilePath python -ArgumentList '-u', (Join-Path $repo 'scripts\frida-eos-stub.py') -WorkingDirectory $repo
    Write-Host '  patches applied (persist until the game exits).'
}
