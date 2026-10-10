#requires -Version 5.1
# Launch New World WITHOUT Steam and WITHOUT EAC.
# Uses an Azoth steam_api64 stub in a private runtime dir. Never overwrites the Steam install.
[CmdletBinding()]
param(
    [string]$InstallRoot = $env:AZOTH_GAME_INSTALL,
    [string]$RuntimeRoot,
    [switch]$Watch,
    [switch]$RefreshExe
)

$ErrorActionPreference = 'Stop'
$SteamAppId = '1063730'
# $PSScriptRoot is NOT bound while param() defaults are evaluated in an advanced
# script under Windows PowerShell 5.1, though it is under pwsh 7. Measured
# 2026-10-09: with the default inside param() the launcher dies with
# "Cannot bind argument to parameter 'Path' because it is an empty string", and
# the client window never appears. Both az.py and scripts/private-run.py invoke
# powershell.exe (5.1), so the whole documented run path was dead. Resolve the
# default here, where $PSScriptRoot is always available.
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path $repo 'private-client\runtime'
}
$repoLauncher = Split-Path -Parent $PSScriptRoot
$stubDll = Join-Path $repoLauncher 'steam_stub\steam_api64.dll'
$stubBuild = Join-Path $repoLauncher 'steam_stub\build.ps1'
$privateRoot = Split-Path -Parent $RuntimeRoot
$profileLocal = Join-Path $privateRoot 'profile\Local'
$profileRoaming = Join-Path $privateRoot 'profile\Roaming'
$stateDir = Join-Path $privateRoot 'state'
$repoTmp = Join-Path $repo '.azoth\tmp'
New-Item -ItemType Directory -Force -Path $repoTmp | Out-Null
$env:TEMP = $repoTmp
$env:TMP = $repoTmp

function Find-GameInstall {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:AZOTH_GAME_INSTALL) { $candidates.Add($env:AZOTH_GAME_INSTALL) }
    $programFiles = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    if ($programFiles) { $candidates.Add((Join-Path $programFiles 'Steam\steamapps\common\New World')) }

    $steamRoots = @()
    foreach ($key in @('HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam')) {
        if (Test-Path $key) {
            $value = Get-ItemProperty -LiteralPath $key
            foreach ($property in @('SteamPath', 'InstallPath')) {
                if ($value.$property) { $steamRoots += $value.$property }
            }
        }
    }
    foreach ($steamRoot in ($steamRoots | Select-Object -Unique)) {
        $steamApps = Join-Path $steamRoot 'steamapps'
        $candidates.Add((Join-Path $steamApps 'common\New World'))
        $libraryFile = Join-Path $steamApps 'libraryfolders.vdf'
        if (Test-Path -LiteralPath $libraryFile) {
            $text = Get-Content -LiteralPath $libraryFile -Raw
            foreach ($match in [regex]::Matches($text, '"(?:path|[0-9]+)"\s+"([^"]+)"')) {
                $library = $match.Groups[1].Value -replace '\\\\', '\'
                $candidates.Add((Join-Path $library 'steamapps\common\New World'))
            }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath (Join-Path $candidate 'Bin64\NewWorld.exe')) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'New World install not found. Install it through Steam or set AZOTH_GAME_INSTALL.'
}

if (-not $InstallRoot) { $InstallRoot = Find-GameInstall }
if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot 'Bin64\NewWorld.exe'))) {
    throw "Game install not found: $InstallRoot"
}
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
$officialExe = (Resolve-Path -LiteralPath (Join-Path $InstallRoot 'Bin64\NewWorld.exe')).Path
$existingClient = Get-CimInstance Win32_Process -Filter "Name = 'NewWorld.exe'"
if ($existingClient) {
    throw "Another NewWorld.exe is running (pid $($existingClient[0].ProcessId)); close it before starting the private client."
}

if (-not (Test-Path -LiteralPath $stubDll)) {
    Write-Host "Building steam_api64 stub (no Steam)..."
    & $stubBuild
    if (-not (Test-Path -LiteralPath $stubDll)) { throw "Stub DLL missing: $stubDll" }
}

$rtBin = Join-Path $RuntimeRoot 'Bin64'
New-Item -ItemType Directory -Force -Path $rtBin | Out-Null
New-Item -ItemType Directory -Force -Path $profileLocal, $profileRoaming, $stateDir | Out-Null

function Link-File([string]$Src, [string]$Dst) {
    if (Test-Path -LiteralPath $Dst) { return }
    try {
        New-Item -ItemType HardLink -Path $Dst -Target $Src | Out-Null
    } catch {
        Copy-Item -LiteralPath $Src -Destination $Dst -Force
    }
}

function Copy-PrivateFile([string]$Src, [string]$Dst) {
    $parent = Split-Path -Parent $Dst
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Dst.copying"
    Copy-Item -LiteralPath $Src -Destination $temporary -Force
    Move-Item -LiteralPath $temporary -Destination $Dst -Force
}

# Game root: junction the large immutable asset tree and copy writable configs.
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
    $dst = Join-Path $RuntimeRoot $name
    $destinationItem = Get-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath $src) -and (-not $destinationItem -or $destinationItem.LinkType)) {
        Copy-PrivateFile $src $dst
    }
}

# Bin64: the executable is always an independent file. Never hardlink a file
# that the private runtime may patch or replace. Other vendor binaries are read-only.
Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'Bin64') -File | ForEach-Object {
    if ($_.Name -eq 'steam_api64.dll') { return }
    if ($_.Name -like '*.eac') { return }
    if ($_.Name -eq 'NewWorld.exe') {
        $privateExe = Join-Path $rtBin $_.Name
        $sourceRecord = Join-Path $stateDir 'client-source.json'
        $sourceHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $installedHash = if (Test-Path -LiteralPath $privateExe) {
            (Get-FileHash -LiteralPath $privateExe -Algorithm SHA256).Hash.ToLowerInvariant()
        } else { '' }
        $record = $null
        if (Test-Path -LiteralPath $sourceRecord) {
            try { $record = Get-Content -LiteralPath $sourceRecord -Raw | ConvertFrom-Json } catch { }
        }

        $previousSourceHash = if ($record.sourceSha256) { $record.sourceSha256 } else { $record.sha256 }
        $previousRuntimeHash = if ($record.runtimeSha256) { $record.runtimeSha256 } else { $previousSourceHash }
        $previousMode = $record.mode
        if (-not $previousMode -and $previousSourceHash -and $installedHash -eq $previousSourceHash) {
            $previousMode = 'synced'
        }

        $refreshManagedExe = (
            $record -and
            $previousMode -eq 'synced' -and
            $installedHash -eq $previousRuntimeHash -and
            $previousSourceHash -ne $sourceHash
        )
        if (-not (Test-Path -LiteralPath $privateExe) -or $RefreshExe -or $refreshManagedExe) {
            Copy-PrivateFile $_.FullName $privateExe
            $installedHash = $sourceHash
        }
        $mode = if ($installedHash -eq $sourceHash) { 'synced' } else { 'preserved' }
        Set-Content -LiteralPath $sourceRecord -Value (@{
            sha256 = $sourceHash
            sourceSha256 = $sourceHash
            runtimeSha256 = $installedHash
            mode = $mode
            install = $InstallRoot
        } | ConvertTo-Json -Compress) -Encoding ascii
        if ($mode -eq 'preserved') {
            Write-Warning "Private NewWorld.exe differs from Steam and was preserved. Use -RefreshExe to replace it."
        }
        return
    }
    Link-File $_.FullName (Join-Path $rtBin $_.Name)
}
Copy-Item -LiteralPath $stubDll -Destination (Join-Path $rtBin 'steam_api64.dll') -Force
Set-Content -LiteralPath (Join-Path $rtBin 'steam_appid.txt') -Value $SteamAppId -Encoding ascii -NoNewline
Set-Content -LiteralPath (Join-Path $RuntimeRoot 'steam_appid.txt') -Value $SteamAppId -Encoding ascii -NoNewline

$exe = Join-Path $rtBin 'NewWorld.exe'
$privateLog = Join-Path $profileLocal 'AGS\New World\Game.log'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $privateLog) | Out-Null
Write-Host "AZOTH PRIVATE LAUNCH (no Steam, no EAC)"
Write-Host "  exe:     $exe"
Write-Host "  stub:    $rtBin\steam_api64.dll"
Write-Host "  assets:  $assetsDst  (junction to install)"
Write-Host "  profile: $privateRoot\profile"
Write-Host "  log:     $privateLog"
Write-Host "  Steam process is NOT required."

# Official EOS "null anticheat client" switch (Epic integration checklist):
# start the exe directly with this set so ClientSDK does not require EAC.
$env:EOS_USE_ANTICHEATCLIENTNULL = '1'
$env:LOCALAPPDATA = $profileLocal
$env:APPDATA = $profileRoaming
$p = Start-Process -FilePath $exe -WorkingDirectory $rtBin -ArgumentList '+lc_listWorlds' -PassThru
$pidFile = Join-Path $stateDir 'game.pid'
Set-Content -LiteralPath $pidFile -Value $p.Id -Encoding ascii -NoNewline
Write-Host "  pid=$($p.Id)  started $(Get-Date -Format o)"
Write-Host "  Watch the project-local Game.log. Memory patches require the private no-EAC process."

if ($Watch) {
    $python = Join-Path $repo '.azoth\venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        throw 'Project Python tools are not installed. Run `python az.py setup` first.'
    }
    Write-Host '  Waiting for NewWorld.exe to map, then applying Frida patches...'
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        try {
            $proc = Get-Process -Id $p.Id -ErrorAction Stop
            if ($proc.WorkingSet64 -gt 50MB) { $ready = $true; break }
        } catch {
            Write-Host '  NewWorld.exe exited before patches'
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
            throw 'NewWorld.exe exited before the patch window.'
        }
    }
    if (-not $ready) {
        Write-Host '  NewWorld.exe still mapping after 120s - attaching anyway'
    }
    $eac = Get-Process -Name 'EasyAntiCheat*' -ErrorAction SilentlyContinue
    $eacService = Get-CimInstance Win32_Service |
        Where-Object { $_.Name -like 'EasyAntiCheat*' -and $_.State -eq 'Running' }
    $eacModule = Get-Process -Id $p.Id -Module -ErrorAction SilentlyContinue |
        Where-Object { $_.ModuleName -like '*EasyAntiCheat*' }
    $actual = Get-CimInstance Win32_Process -Filter "ProcessId = $($p.Id)"
    if ($eac -or $eacService -or $eacModule -or -not $actual -or $actual.ExecutablePath -ne $exe) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        throw 'Private process validation failed or EAC is active; the client was stopped without memory tooling.'
    }
    Write-Host '  DTLS verify bypass...'
    & $python -u (Join-Path $repo 'services\launcher\runtime-tools\frida-trust-patch.py')
    if ($LASTEXITCODE -ne 0) { Write-Host '  trust-patch FAILED' }
    Write-Host '  Force 4th spawn gate (13->14 call-site NOP)...'
    & $python -u (Join-Path $repo 'services\launcher\runtime-tools\patch-spawn-gate.py')
    if ($LASTEXITCODE -ne 0) { Write-Host '  spawn-gate-force FAILED' }
    # ClientContext gate. CORRECTED 2026-09-27: the archived notion of this
    # patch was INVERTED. LoadContextAndLevel passes the virtual predicate's
    # result ([pGame+0x28]->vtable[0x88]) to clientContext->Initialize as its
    # 7th argument, and Initialize SELF-CLEANS when that value is 0
    # (0x14171ba31 cmp byte [rsp+0x110],0 / jne skip / call 0x1416835B0 =
    # the '[ClientContext] Cleanup()' log). The predicate returns 0, so the
    # context died in the same millisecond and every state bundle was dropped
    # with 'clientContext == nullptr'. Forcing the flag to 0 (the old
    # scripts/patch-context-gate.py wrote 31 DB 90 = xor ebx, ebx) made it
    # WORSE. The correct patch sets it to 1 and NOPs the failure branch.
    # VERIFIED: the Initialize -> Cleanup pair disappears from Game.log.
    Write-Host '  ClientContext predicate flag -> ok (not cleanup)...'
    & $python -u (Join-Path $repo 'services\launcher\runtime-tools\patch-predicate-flag.py')
    if ($LASTEXITCODE -ne 0) { Write-Host '  predicate-flag FAILED' }
    # Per-state watchdog: without it the client forces connection_ingame_timeout
    # even when the world is loaded and the replay heartbeat is flowing.
    Write-Host '  InGame watchdog (no forced disconnect)...'
    & $python -u (Join-Path $repo 'services\launcher\runtime-tools\patch-timeout-watchdog.py')
    if ($LASTEXITCODE -ne 0) { Write-Host '  timeout-watchdog FAILED' }
    Write-Host '  Anticheat gate byte-patch...'
    & $python -u (Join-Path $repo 'services\launcher\runtime-tools\frida-anticheat-patch.py')
    if ($LASTEXITCODE -ne 0) { Write-Host '  anticheat-patch FAILED' }
    if ($env:AZOTH_NATURAL_SPAWN -eq '1') {
        Write-Host '  Natural spawn ladder enabled (state patches skipped)'
    } else {
        Write-Host '  Force actor/spawn ladder (skip 2min timeout)...'
        & $python -u (Join-Path $repo 'services\launcher\runtime-tools\frida-rep-force-ladder.py')
        if ($LASTEXITCODE -ne 0) { Write-Host '  ladder-force FAILED' }
    }
    Write-Host '  EOS ClientSDK stubs (window must stay open)...'
    # MUST be a detached, persistent process: the stub holds live Frida
    # NativeCallbacks, and it silently dying = @mm_csdkerr_disconnect (2)
    # 3.5s into InGame (2026-09-20: watchdog launched it via & which
    # returned immediately; stub died with the launcher window).
    $eos = Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList '-u', (Join-Path $repo 'services\launcher\runtime-tools\frida-eos-stub.py') -WorkingDirectory $repo -PassThru
    Set-Content -LiteralPath (Join-Path $stateDir 'eos.pid') -Value $eos.Id -Encoding ascii -NoNewline
    Write-Host '  patches applied (persist until the game exits).'
}

try { $p.WaitForExit() } finally {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $eosPidFile = Join-Path $stateDir 'eos.pid'
    if (Test-Path -LiteralPath $eosPidFile) {
        $eosPid = Get-Content -LiteralPath $eosPidFile -Raw
        if ($eosPid -match '^\d+$') {
            Stop-Process -Id ([int]$eosPid) -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $eosPidFile -Force -ErrorAction SilentlyContinue
    }
}
