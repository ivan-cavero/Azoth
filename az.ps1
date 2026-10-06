param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $AzothArgs
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$lockPath = Join-Path $repoRoot 'toolchain.lock.json'
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$pythonSpec = $lock.runtime.python
$pythonRoot = Join-Path $repoRoot ('.azoth/python/' + $pythonSpec.version)
$pythonExe = Join-Path $pythonRoot 'python.exe'
$venvPython = Join-Path $repoRoot '.azoth/venv/Scripts/python.exe'
$downloads = Join-Path $repoRoot '.azoth/downloads'
$tempRoot = Join-Path $repoRoot '.azoth/tmp'
$isSetup = $AzothArgs.Count -gt 0 -and $AzothArgs[0] -eq 'setup'

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf) -and $isSetup) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Force -Path $downloads, $pythonRoot, $tempRoot | Out-Null
    $env:TEMP = $tempRoot
    $env:TMP = $tempRoot
    $installer = Join-Path $downloads ('python-' + $pythonSpec.version + '-amd64.exe')

    if (-not (Test-Path -LiteralPath $installer -PathType Leaf) -or
        (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $pythonSpec.sha256) {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        Write-Host "Downloading CPython $($pythonSpec.version) from python.org..."
        Invoke-WebRequest -Uri $pythonSpec.url -OutFile $installer -UseBasicParsing
    }

    $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $pythonSpec.sha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $installer -Force
        throw "Python installer SHA-256 mismatch: expected $($pythonSpec.sha256), got $actualHash"
    }

    $installerArgs = @(
        '/quiet',
        'InstallAllUsers=0',
        "TargetDir=$pythonRoot",
        'PrependPath=0',
        'Include_launcher=0',
        'Include_test=0',
        'Include_doc=0',
        'Include_tcltk=0',
        'Include_tools=0',
        'Include_pip=1',
        'Shortcuts=0'
    )
    & $installer @installerArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw "Project-local Python installation failed (exit $LASTEXITCODE)."
    }
}

if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonExe = $venvPython
}
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Project Python is not installed. Run .\az.ps1 setup to prepare the local toolchain.'
}

if ($AzothArgs.Count -eq 0) {
    $AzothArgs = @('--help')
}
& $pythonExe (Join-Path $repoRoot 'az.py') @AzothArgs
exit $LASTEXITCODE
