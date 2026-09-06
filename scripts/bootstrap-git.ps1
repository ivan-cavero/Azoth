#requires -Version 5.1
# Recreate local submodule gitlinks if someone cloned without --recurse.
# First-time init already happened; this only repairs relative URLs.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
git submodule sync --recursive
git submodule update --init --recursive
git submodule status
