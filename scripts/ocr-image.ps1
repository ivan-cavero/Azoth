#requires -Version 5.1
<#
.SYNOPSIS
  OCR a PNG with the Windows built-in engine (no install, no new deps).
.DESCRIPTION
  The agent model cannot read images; this turns a screenshot into text so the
  game screen can be inspected. Engine = Windows.Media.Ocr (WinRT), language
  from the user profile (es-ES here).
.EXAMPLE
  powershell -NoProfile -File scripts\ocr-image.ps1 shot.png es-ES
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)][string]$Path,
    [string]$Language = '',
    [string]$Find = '',
    [switch]$All
)
$ErrorActionPreference = 'Stop'
$Path = (Resolve-Path -LiteralPath $Path).Path

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Await($op, $type) {
    $net = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $net.Wait(-1) | Out-Null
    $net.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media, ContentType = WindowsRuntime] | Out-Null

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = $null
if ($Language) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Language)) }
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { throw 'no OCR engine available' }

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
if ($Find -or $All) {
    # Word boxes, so the caller can turn a label into click coordinates.
    # Coordinates are in the OCR'd image's pixels (divide by the prep scale).
    foreach ($line in $result.Lines) {
        foreach ($word in $line.Words) {
            if ($All -or $word.Text -like "*$Find*") {
                $r = $word.BoundingRect
                Write-Output ("{0}|{1:N0},{2:N0},{3:N0},{4:N0}" -f $word.Text, $r.X, $r.Y, $r.Width, $r.Height)
            }
        }
    }
}
else {
    foreach ($line in $result.Lines) { $line.Text }
}
