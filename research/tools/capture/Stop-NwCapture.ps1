#requires -Version 5.1
# Writes STOP into the last session so the watcher and pktmon exit.
$CaptureDir = $PSScriptRoot
$last = Join-Path $CaptureDir '.last-session'
if (-not (Test-Path $last)) {
    Write-Host 'No .last-session' -ForegroundColor Yellow
    Read-Host 'ENTER'
    exit 1
}
$session = (Get-Content $last -Raw).Trim()
'stop-external' | Set-Content (Join-Path $session 'STOP') -Encoding UTF8
Write-Host "STOP -> $session"
Read-Host 'ENTER'
