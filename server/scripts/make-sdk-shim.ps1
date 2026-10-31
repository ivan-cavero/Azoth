<#
.SYNOPSIS
  Reproduce server/target/sdk-shim/: the Windows API import libraries that the
  pinned Rust toolchain does not ship and that this machine's Windows SDK does
  not provide.

.DESCRIPTION
  Not derivable from the Rust toolchain. The shim is a copy of the import
  libraries from an LLVM-MinGW install (WinGet package
  MartinStorsjo.LLVM-MinGW.UCRT); the files are byte-identical. If the Windows
  SDK is installed instead, do not use this script: point LIB at the SDK's
  Lib\um\x64 and Lib\ucrt\x64.

  The link also needs the MSVC CRT (msvcrt.lib, vcruntime.lib), which ships with
  the MSVC toolset; -EmitLib finds it with vswhere and prints the LIB value.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File server\scripts\make-sdk-shim.ps1 -EmitLib
#>
[CmdletBinding()]
param(
  [string]$MinGwRoot,
  [string]$OutDir = (Join-Path $PSScriptRoot '..\target\sdk-shim'),
  [switch]$EmitLib
)

$ErrorActionPreference = 'Stop'

# LLVM-MinGW import libraries the link line asks for, shim name -> MinGW name.
$libs = [ordered]@{
  kernel32 = 'libkernel32.a'
  ucrt     = 'libucrt.a'
  ntdll    = 'libntdll.a'
  userenv  = 'libuserenv.a'
  ws2_32   = 'libws2_32.a'
  dbghelp  = 'libdbghelp.a'
  advapi32 = 'libadvapi32.a'
}

if (-not $MinGwRoot) {
  $pkgs = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
  Get-ChildItem $pkgs -Directory -Filter 'MartinStorsjo.LLVM-MinGW.UCRT*' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem $_.FullName -Directory -ErrorAction SilentlyContinue } |
    Where-Object { Test-Path (Join-Path $_.FullName 'x86_64-w64-mingw32\lib') } |
    Select-Object -First 1 |
    ForEach-Object { $MinGwRoot = $_.FullName }
}
if (-not $MinGwRoot) {
  throw 'Pass -MinGwRoot <llvm-mingw directory>; no LLVM-MinGW found under WinGet packages.'
}

$srcDir = Join-Path $MinGwRoot 'x86_64-w64-mingw32\lib'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

foreach ($name in $libs.Keys) {
  $src = Join-Path $srcDir $libs[$name]
  if (-not (Test-Path $src)) { throw "missing $src" }
  Copy-Item $src (Join-Path $OutDir "$name.lib") -Force
}
$OutDir = (Resolve-Path $OutDir).Path
Write-Host "shim -> $OutDir"

if ($EmitLib) {
  $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  $msvc = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath 2>$null
  if (-not $msvc) { throw 'MSVC tools not found; install the "Desktop development with C++" workload.' }
  $crt = Get-ChildItem (Join-Path $msvc 'VC\Tools\MSVC') -Directory |
    Sort-Object Name -Descending | Select-Object -First 1 |
    ForEach-Object { Join-Path $_.FullName 'lib\x64' }
  if (-not (Test-Path $crt)) { throw "no CRT libs under $crt" }
  Write-Host "LIB=$OutDir;$crt"
}
