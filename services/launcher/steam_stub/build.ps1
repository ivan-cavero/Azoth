#requires -Version 5.1
# Build Azoth steam_api64 stub v2 (minimal). Prefers MSVC (cl), falls back to gcc/clang.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$src = Join-Path $here 'src\stub.c'
$def = Join-Path $here 'src\stub.def'
$dll = Join-Path $here 'steam_api64.dll'
$tmpObj = Join-Path $env:TEMP 'azoth_stub.obj'

function Find-MSVC {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vs = & $vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools -property installationPath 2>$null
        if ($vs) {
            $cl = Get-ChildItem -Path (Join-Path $vs 'VC\Tools\MSVC') -Recurse -Filter cl.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match 'x64' } | Select-Object -First 1
            if ($cl) { return $cl.FullName }
        }
    }
    foreach ($p in @('C:\Program Files\Microsoft Visual Studio', 'C:\Program Files (x86)\Microsoft Visual Studio')) {
        if (Test-Path $p) {
            $cl = Get-ChildItem -Path $p -Recurse -Filter cl.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match 'x64' } | Select-Object -First 1
            if ($cl) { return $cl.FullName }
        }
    }
    return $null
}

$cl = Find-MSVC
if ($cl) {
    Write-Host "Using MSVC: $cl"
    $vsRoot = Split-Path (Split-Path (Split-Path (Split-Path $cl)))
    # $vsRoot = ...\VC\Tools\MSVC\<ver> -> up to VS installation root
    $vsInstall = Split-Path (Split-Path (Split-Path $vsRoot))
    $vcvars = Join-Path $vsInstall 'VC\Auxiliary\Build\vcvars64.bat'
    if (-not (Test-Path $vcvars)) { $vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat' }
    $cmd = "`"$vcvars`" >nul && cl /nologo /LD /O2 /W3 /Fo`"$env:TEMP\azoth_stub.obj`" /Fe`"$dll`" `"$src`" /link /DEF:`"$def`" /OUT:`"$dll`""
    Write-Host $cmd
    cmd /c $cmd
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dll)) { throw 'cl failed' }
} else {
    $cc = Get-Command clang -ErrorAction SilentlyContinue
    if (-not $cc) { $cc = Get-Command gcc -ErrorAction SilentlyContinue }
    if (-not $cc) { throw 'No compiler: install MSVC Build Tools (preferred) or llvm-mingw/gcc' }
    Write-Host "Using $($cc.Name): $($cc.Source)"
    & $cc.Source -shared -O2 -s -o $dll $src
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dll)) { throw 'cc failed' }
}
Write-Host "built $dll ($((Get-Item $dll).Length) bytes)"
