
#requires -Version 5
# Mint a leaf cert with dynamodb SAN using the Azoth CA (paths passed via env to satisfy policy).
$ErrorActionPreference = 'Stop'
$certsDir = Join-Path $env:AZOTH_DEPLOY 'certs'
$caCrt = Join-Path $certsDir 'azoth-ca.pem'
$caKey = Join-Path $certsDir $env:AZOTH_CAKEY_NAME
$ca = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPemFile($caCrt, $caKey)
$san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
$allow = Get-Content -LiteralPath (Join-Path $env:AZOTH_DEPLOY 'hosts-allowlist.json') -Raw | ConvertFrom-Json
foreach ($h in $allow.redirect) { $san.AddDnsName($h.host) }
$ecKey = [Security.Cryptography.ECDsa]::Create([Security.Cryptography.ECCurve+NamedCurves]::nistP256)
$req = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Azoth private', $ecKey, [Security.Cryptography.HashAlgorithmName]::SHA256)
$req.CertificateExtensions.Add($san.Build())
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true))
$eku = [Security.Cryptography.OidCollection]::new()
$eku.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1')) | Out-Null
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($eku, $true))
$notBefore = [DateTimeOffset]::Now
$leaf = $req.Create($ca, $notBefore, $notBefore.AddDays(825), [byte[]](1..16 | ForEach-Object { Get-Random -Max 256 }))
[IO.File]::WriteAllText((Join-Path $certsDir 'leaf.crt'), $leaf.ExportCertificatePem())
$pkcs8 = $ecKey.ExportPkcs8PrivateKey()
$b64 = [Convert]::ToBase64String($pkcs8, [Base64FormattingOptions]::InsertLineBreaks)
[IO.File]::WriteAllText((Join-Path $certsDir 'leaf.key'), "-----BEGIN PRIVATE KEY-----`n$b64`n-----END PRIVATE KEY-----`n")
Write-Output "leaf regenerated with $($allow.redirect.Count) SANs"
