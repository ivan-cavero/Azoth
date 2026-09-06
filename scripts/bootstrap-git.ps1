#requires -Version 5.1
# Init/sync submodules from GitHub (Azoth-Research, Azoth-Emulator, Azoth-Launcher).
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
git submodule sync --recursive
git submodule update --init --recursive
git submodule status
