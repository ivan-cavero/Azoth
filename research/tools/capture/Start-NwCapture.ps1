#requires -Version 5.1
# One elevated window: Game.log watcher + pktmon. Waits until ENTER after play.
[CmdletBinding()]
param(
    [switch]$SkipPktmon,
    [switch]$SkipStatic,
    [switch]$SmokeTest,
    [int]$WaitSeconds = 0,
    [string]$SessionName,
    [string]$PythonExe,
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'
# pktmon writes "ERROR: Packet Monitor is not running" on stop-when-idle.
# Do not treat native stderr as a terminating error (PS 7+).
$PSNativeCommandUseErrorActionPreference = $false
$CaptureDir = $PSScriptRoot
if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $CaptureDir '..\..')).Path
}

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
        IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-Python([string]$Hint) {
    $candidates = @()
    if ($Hint) { $candidates += $Hint }
    try {
        $exe = & python -c "import sys; print(sys.executable)" 2>$null
        if ($exe) { $candidates += $exe.Trim() }
    } catch {}
    $candidates += @(
        "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe",
        "$env:LOCALAPPDATA\Python\pythoncore-3.13-64\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c) -and ($c -notmatch 'WindowsApps')) { return $c }
    }
    throw "No real python.exe found (avoid the WindowsApps stub)."
}

function Start-DetachedProcess {
    param([string]$FilePath, [string]$Arguments, [string]$WorkDir)
    $si = New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName = $FilePath
    $si.Arguments = $Arguments
    $si.WorkingDirectory = $WorkDir
    $si.UseShellExecute = $true
    $si.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($si)
}

function Invoke-Pktmon([string]$ArgLine) {
    # Single string to cmd.exe — PowerShell must not parse pktmon flags.
    $out = & cmd.exe /c "pktmon $ArgLine 2>&1"
    return @{ Code = [int]$LASTEXITCODE; Text = (($out | Out-String).Trim()) }
}

function Wait-End([string]$Msg) {
    Write-Host ''
    Write-Host $Msg -ForegroundColor Yellow
    try { [void](Read-Host 'Press ENTER to close') } catch { Start-Sleep -Seconds 6 }
}

$needAdmin = -not $SkipPktmon -and -not $SmokeTest -and $WaitSeconds -le 0
if ($needAdmin -and -not (Test-Admin)) {
    $py = Resolve-Python $PythonExe
    $argList = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit',
        '-File', $PSCommandPath,
        '-SkipStatic',
        '-PythonExe', $py,
        '-RepoRoot', $RepoRoot
    )
    if ($SessionName) { $argList += @('-SessionName', $SessionName) }
    Write-Host 'Requesting Administrator (required for NIC capture)...' -ForegroundColor Yellow
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList
    exit 0
}

$session = $null
$pktmonOn = $false
try {
    Set-Location $RepoRoot
    $PythonExe = Resolve-Python $PythonExe
    $PythonScript = Join-Path $CaptureDir 'nw_capture.py'
    if (-not (Test-Path -LiteralPath $PythonScript)) { throw "Missing $PythonScript" }

    if (-not $SessionName) {
        $SessionName = 'live_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
    }
    $session = Join-Path $RepoRoot "sessions\$SessionName"
    New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot 'sessions') | Out-Null
    Add-Content (Join-Path $RepoRoot 'sessions\_launcher.log') "$(Get-Date -Format o) start $SessionName admin=$(Test-Admin)" -Encoding UTF8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '  NEW WORLD capture  (log + NIC). Stays open until ENTER.' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host "  python  $PythonExe"
    Write-Host "  session $session"
    Write-Host "  admin   $(Test-Admin)"
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''

    $initOut = & $PythonExe -u $PythonScript init --repo $RepoRoot --session $session 2>&1
    $initOut | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $session 'session.json'))) {
        throw "init failed: $initOut"
    }
    $session | Set-Content (Join-Path $CaptureDir '.last-session') -Encoding UTF8

    $watchArgs = "-u `"$PythonScript`" watch --session `"$session`" --parent-pid 0"
    Write-Host 'Starting watcher...' -ForegroundColor Cyan
    $null = Start-DetachedProcess -FilePath $PythonExe -Arguments $watchArgs -WorkDir $RepoRoot
    Start-Sleep -Seconds 2
    $watching = Join-Path $session 'WATCHING'
    if (-not (Test-Path -LiteralPath $watching)) {
        $runner = Join-Path $session 'logs\capture-runner.log'
        $tail = if (Test-Path $runner) { Get-Content $runner -Raw } else { '(no log)' }
        throw "Watcher did not start.`n$tail"
    }
    Write-Host "Watcher OK pid=$((Get-Content $watching -Raw).Trim())" -ForegroundColor Green

    $pktmonOn = $false
    $netDir = Join-Path $session 'network'
    $etl = Join-Path $netDir 'pktmon.etl'
    $pcap = Join-Path $netDir 'pktmon.pcapng'
    if (-not $SkipPktmon -and -not $SmokeTest -and (Test-Admin)) {
        Write-Host 'Starting pktmon on this window...' -ForegroundColor Cyan
        New-Item -ItemType Directory -Force -Path $netDir | Out-Null
        try {
            [void](Invoke-Pktmon 'stop')
            Start-Sleep -Milliseconds 300
            [void](Invoke-Pktmon 'filter remove')
            [void](Invoke-Pktmon 'filter add NW-HTTPS -t TCP -p 443')
            [void](Invoke-Pktmon 'filter add NW-UDP -t UDP')
            [void](Invoke-Pktmon 'filter add NW-DNS -t UDP -p 53')
            $start = Invoke-Pktmon "start --capture --comp nics --pkt-size 0 --file-name `"$etl`" --file-size 1024 --log-mode circular"
            if ($start.Code -eq 0) {
                $pktmonOn = $true
                Write-Host 'NIC OK: TCP/443 + UDP + DNS.' -ForegroundColor Green
            } else {
                Write-Host "pktmon start failed (code $($start.Code)). Continuing with Game.log." -ForegroundColor Yellow
                if ($start.Text) { Write-Host $start.Text -ForegroundColor DarkYellow }
            }
        } catch {
            Write-Host "pktmon setup error (continuing with Game.log): $($_.Exception.Message)" -ForegroundColor Yellow
            $pktmonOn = $false
        }
    }

    if ($SmokeTest) {
        Start-Sleep -Seconds 4
        if (-not (Test-Path (Join-Path $session 'STATUS.txt'))) { throw 'no STATUS.txt' }
        'smoke' | Set-Content (Join-Path $session 'STOP') -Encoding UTF8
        Start-Sleep -Seconds 2
        Write-Host 'SmokeTest OK' -ForegroundColor Green
        exit 0
    }

    if ($WaitSeconds -gt 0) {
        Write-Host "Test wait $WaitSeconds s..."
        Start-Sleep -Seconds $WaitSeconds
    } else {
        Write-Host ''
        Write-Host '************************************************************' -ForegroundColor Green
        Write-Host '  RECORDING. Do not press ENTER yet.' -ForegroundColor Green
        Write-Host '  1. Open Steam -> New World' -ForegroundColor Green
        Write-Host '  2. Log in, enter the world, play ~10 minutes' -ForegroundColor Green
        Write-Host '  3. Come back here and press ENTER' -ForegroundColor Green
        Write-Host '************************************************************' -ForegroundColor Green
        Write-Host ''
        $donePlay = $false
        while (-not $donePlay) {
            $st = Join-Path $session 'STATUS.txt'
            if (Test-Path -LiteralPath $st) {
                Write-Host '------------------------------------------------------------' -ForegroundColor DarkGray
                Write-Host (Get-Content -LiteralPath $st -Raw)
            }
            Write-Host 'ENTER = finished playing.' -ForegroundColor Yellow
            try {
                $until = (Get-Date).AddSeconds(10)
                while ((Get-Date) -lt $until) {
                    if ([Console]::KeyAvailable) {
                        $k = [Console]::ReadKey($true)
                        if ($k.Key -eq 'Enter' -or $k.Key -eq 'Q') { $donePlay = $true; break }
                    }
                    Start-Sleep -Milliseconds 250
                }
            } catch {
                Read-Host 'Press ENTER when you have FINISHED playing'
                $donePlay = $true
            }
        }
    }

    Write-Host "`nStopping capture..." -ForegroundColor Yellow
    'stop' | Set-Content (Join-Path $session 'STOP') -Encoding UTF8
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline -and (Test-Path $watching)) { Start-Sleep -Milliseconds 400 }

    if ($pktmonOn) {
        Write-Host 'Stopping pktmon and converting pcap...' -ForegroundColor Cyan
        [void](Invoke-Pktmon 'stop')
        [void](Invoke-Pktmon 'filter remove')
        if (Test-Path -LiteralPath $etl) {
            $conv = Invoke-Pktmon "etl2pcap `"$etl`" --out `"$pcap`""
            if ($conv.Text) { Write-Host $conv.Text }
        }
    }

    Write-Host 'Writing REPORT.md...' -ForegroundColor Cyan
    & $PythonExe -u $PythonScript report --session $session
    $re = Join-Path $RepoRoot 'tools\re'
    if (Test-Path -LiteralPath $pcap) {
        & $PythonExe -u (Join-Path $re 'net.py') analyze $pcap --out (Join-Path $session 'network\pktmon.analysis.json')
    } else {
        Write-Host 'No pcap. Game.log is still useful if you played.' -ForegroundColor Yellow
    }
    & $PythonExe -u (Join-Path $re 'endpoints.py') --session $session --out (Join-Path $session 'extracted\endpoints_catalog.json')
    Write-Host ''
    Write-Host 'Done:' -ForegroundColor Green
    Write-Host "  $session\REPORT.md"
    Write-Host "  $session\metrics.json"
    Write-Host "  $session\logs\events.jsonl"
    if (Test-Path $pcap) { Write-Host "  $pcap" }
    Wait-End 'Capture finished.'
} catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    try {
        if ($session) { 'stop' | Set-Content (Join-Path $session 'STOP') -Encoding UTF8 }
        if ($pktmonOn) { [void](Invoke-Pktmon 'stop') }
    } catch {}
    Wait-End 'Failed. Copy this error if you paste it in chat.'
    exit 1
}
