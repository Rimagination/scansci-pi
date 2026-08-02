[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$BuildDir,
    [Parameter(Mandatory)]
    [string]$Version,
    [Parameter(Mandatory)]
    [string]$BuildId,
    [Parameter(Mandatory)]
    [string]$OutputDir,
    [switch]$RequireSignature
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = (Resolve-Path -LiteralPath $BuildDir).Path
$output = [System.IO.Path]::GetFullPath($OutputDir)
$scriptPath = Join-Path $projectRoot "installer\ScanSci.iss"
$exe = Join-Path $source "ScanSci.exe"

function Get-SigningConfiguration {
    if (-not $RequireSignature) {
        return $null
    }

    # Keep release credentials and certificate selection out of source control.
    # A formal build is allowed to run only on the release machine where an
    # Authenticode certificate is installed in the current user's My store.
    $thumbprint = ([string]$env:SCANSCI_SIGNING_CERT_THUMBPRINT).Replace(" ", "").Trim()
    $timestampUrl = ([string]$env:SCANSCI_TIMESTAMP_URL).Trim()
    if (-not $thumbprint) {
        throw "Formal signing requires SCANSCI_SIGNING_CERT_THUMBPRINT to identify a CurrentUser\\My code-signing certificate."
    }
    if ($thumbprint -notmatch '^[A-Fa-f0-9]{40}$') {
        throw "SCANSCI_SIGNING_CERT_THUMBPRINT must be a 40-character SHA-1 certificate thumbprint."
    }
    if (-not $timestampUrl) {
        throw "Formal signing requires SCANSCI_TIMESTAMP_URL (an HTTPS RFC 3161 timestamp service)."
    }
    try {
        $timestampUri = [uri]$timestampUrl
    } catch {
        throw "SCANSCI_TIMESTAMP_URL is not a valid absolute HTTPS URL."
    }
    if (-not $timestampUri.IsAbsoluteUri -or $timestampUri.Scheme -ne "https") {
        throw "SCANSCI_TIMESTAMP_URL must be an absolute HTTPS URL."
    }

    $certificate = Get-ChildItem -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -ErrorAction SilentlyContinue
    if (-not $certificate) {
        throw "The signing certificate $thumbprint was not found in Cert:\CurrentUser\My."
    }
    if (-not $certificate.HasPrivateKey) {
        throw "The signing certificate $thumbprint does not expose a private key to this release account."
    }
    if ($certificate.NotAfter -le (Get-Date)) {
        throw "The signing certificate $thumbprint is expired."
    }

    $kitRoots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "$env:ProgramFiles\Windows Kits\10\bin"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }
    $kitCandidates = foreach ($kitRoot in $kitRoots) {
        Get-ChildItem -LiteralPath $kitRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" }
    }
    $signToolCandidates = @(
        (Get-Command signtool.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        $kitCandidates
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    if (-not $signToolCandidates) {
        throw "Formal signing requires SignTool.exe from the Windows SDK or Visual Studio Developer PowerShell."
    }

    return [pscustomobject]@{
        Thumbprint = $thumbprint
        TimestampUrl = $timestampUri.AbsoluteUri
        SignTool = ($signToolCandidates | Select-Object -First 1)
    }
}

function Sign-Artifact {
    param(
        [Parameter(Mandatory)]
        [string]$Artifact,
        [Parameter(Mandatory)]
        [object]$Signing
    )

    & $Signing.SignTool sign /fd SHA256 /sha $Signing.Thumbprint /tr $Signing.TimestampUrl /td SHA256 $Artifact
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool failed with exit code $LASTEXITCODE for $Artifact"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Artifact
    if ($signature.Status -ne "Valid") {
        throw "Authenticode verification failed for $Artifact; status: $($signature.Status)"
    }
    return $signature
}

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Packaged ScanSci executable was not found: $exe"
}
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Inno Setup script was not found: $scriptPath"
}
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.-]+)?$') {
    throw "Version must be SemVer-compatible: $Version"
}
if ($BuildId -notmatch '^[0-9A-Za-z._+-]+$') {
    throw "BuildId may only contain letters, numbers, dots, underscores, plus signs, and hyphens."
}

$signing = Get-SigningConfiguration
$sourceSignature = Get-AuthenticodeSignature -LiteralPath $exe
if ($signing) {
    # Sign the packaged executable first so that the copy extracted by a user
    # remains signed, then sign the installer that transports it.
    $sourceSignature = Sign-Artifact -Artifact $exe -Signing $signing
}

$isccCandidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
if (-not $isccCandidates) {
    throw "Inno Setup 6 (ISCC.exe) is required to build the Windows installer."
}

New-Item -ItemType Directory -Force -Path $output | Out-Null
$iscc = $isccCandidates | Select-Object -First 1
$arguments = @(
    "/DSourceDir=$source",
    "/DOutputDir=$output",
    "/DAppVersion=$Version",
    "/DBuildId=$BuildId",
    $scriptPath
)
& $iscc @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$installer = Join-Path $output "ScanSci-$Version-windows-x64-setup.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Inno Setup completed without the expected installer: $installer"
}

$installerSignature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signing) {
    $installerSignature = Sign-Artifact -Artifact $installer -Signing $signing
}
if ($RequireSignature -and ($sourceSignature.Status -ne "Valid" -or $installerSignature.Status -ne "Valid")) {
    throw "Formal release requires valid Authenticode signatures for both ScanSci.exe and the installer."
}

$manifest = [ordered]@{
    schema_version = 1
    product = "ScanSci"
    version = $Version
    build_id = $BuildId
    generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    source_directory = $source
    source_executable_sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    source_executable_authenticode_status = [string]$sourceSignature.Status
    installer_path = $installer
    installer_sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    installer_bytes = (Get-Item -LiteralPath $installer).Length
    authenticode_status = [string]$installerSignature.Status
    signature_required = [bool]$RequireSignature
}
$manifestPath = Join-Path $output "installer-manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Output $installer
Write-Output $manifestPath
