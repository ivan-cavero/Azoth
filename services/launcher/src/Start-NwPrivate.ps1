#requires -Version 5.1
# Launch New World WITHOUT Steam and WITHOUT EAC.
# Uses an Azoth steam_api64 stub in a private runtime dir. Never overwrites the Steam install.
[CmdletBinding()]
param(
    [string]$InstallRoot = "C:\Program Files (x86)\Steam\steamapps\common\New World",
    [string]$RuntimeRoot = $(Join-Path $env:LOCALAPPDATA 'Azoth\game')
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

$p = Start-Process -FilePath $exe -WorkingDirectory $rtBin -ArgumentList '+lc_listWorlds' -PassThru
Write-Host "  pid=$($p.Id)  started $(Get-Date -Format o)"
Write-Host "  Watch Game.log. Green: Channel service uri, no EasyAntiCheat_EOS.exe."
