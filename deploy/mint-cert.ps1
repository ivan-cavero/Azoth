#requires -Version 7
<#
.SYNOPSIS
  Mint the Azoth private leaf cert with Caddy's local CA (needs admin only
  to read nothing — actually no admin needed at all: CA files live in the
  user's own %APPDATA%\Caddy; output goes to deploy/certs, gitignored).
.DESCRIPTION
  Reads Caddy's local root (crt+key PEM), issues a leaf with every
  hosts-allowlist.json redirect host as SAN, writes deploy/certs/leaf.*.
  Caddyfile.json loads these directly (no automation/on-demand involved).
#>
[CmdletBinding()]
param(
    [string]$DeployDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)
$ErrorActionPreference = 'Stop'

$allow = Get-Content -LiteralPath (Join-Path $DeployDir 'hosts-allowlist.json') -Raw | ConvertFrom-Json
$hosts = @($allow.redirect | ForEach-Object { $_.host })
Write-Output "hosts: $($hosts.Count)"

$caCrt = Join-Path $env:APPDATA 'Caddy\pki\authorities\local\root.crt'
$caKey = Join-Path $env:APPDATA 'Caddy\pki\authorities\local\root.key'
if (-not (Test-Path $caCrt) -or -not (Test-Path $caKey)) { throw "Caddy local CA not found ($caCrt). Run caddy once first." }

$ca = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPemFile($caCrt, $caKey)
$san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
foreach ($h in $hosts) { $san.AddDnsName($h) }
$ecKey = [Security.Cryptography.ECDsa]::Create(
    [Security.Cryptography.ECCurve+NamedCurves]::nistP256)
$req = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
    'CN=Azoth private', $ecKey,
    [Security.Cryptography.HashAlgorithmName]::SHA256)
$req.CertificateExtensions.Add($san.Build())
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true))
$eku = [Security.Cryptography.OidCollection]::new()
$eku.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1')) | Out-Null
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($eku, $true))
$notBefore = [DateTimeOffset]::Now
$leaf = $req.Create($ca, $notBefore, $notBefore.AddDays(825), [byte[]](1..16 | ForEach-Object { Get-Random -Max 256 }))

$certsDir = Join-Path $DeployDir 'certs'
New-Item -ItemType Directory -Force -Path $certsDir | Out-Null
$leafCrt = Join-Path $certsDir 'leaf.crt'
$leafKey = Join-Path $certsDir 'leaf.key'
[IO.File]::WriteAllText($leafCrt, $leaf.ExportCertificatePem())
$pkcs8 = $ecKey.ExportPkcs8PrivateKey()
$b64 = [Convert]::ToBase64String($pkcs8, [Base64FormattingOptions]::InsertLineBreaks)
[IO.File]::WriteAllText($leafKey, "-----BEGIN PRIVATE KEY-----`n$b64`n-----END PRIVATE KEY-----`n")
Write-Output "wrote $leafCrt"
Write-Output "wrote $leafKey"
Write-Output "thumbprint: $($leaf.Thumbprint)"
