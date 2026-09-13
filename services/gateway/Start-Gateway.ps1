#requires -Version 5.1
# Run Azoth gateway minimo (stdlib only, no pip needed).
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:PYTHONPATH = (Join-Path $here 'src')
$py = $env:LOCALAPPDATA + '\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
& $py -m azoth_gateway @args
