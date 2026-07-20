[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$BuildDir,
    [Parameter(Mandatory)]
    [string]$Version,
    [Parameter(Mandatory)]
    [string]$PackageUrl,
    [string]$OutputDir = "",
    [string]$Channel = "stable"
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = [System.IO.Path]::GetFullPath($BuildDir)
if (-not (Test-Path -LiteralPath (Join-Path $source "ScanSci.exe") -PathType Leaf)) {
    throw "ScanSci desktop build was not found: $source"
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $projectRoot "release"
}
$releaseRoot = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
$archive = Join-Path $releaseRoot "ScanSci-$Version-windows-x64.zip"
$manifest = Join-Path $releaseRoot "stable.json"
Compress-Archive -Path (Join-Path $source "*") -DestinationPath $archive -CompressionLevel Optimal -Force
$sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$payload = [ordered]@{
    version = $Version
    title = "ScanSci $Version"
    channel = $Channel
    published_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    notes = @(
        [ordered]@{ title = "Desktop"; items = @("Version status, release notes, and verified installation are available.") }
    )
    windows = [ordered]@{
        url = $PackageUrl
        sha256 = $sha256
        archive = [System.IO.Path]::GetFileName($archive)
    }
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifest -Encoding utf8
Write-Output $archive
Write-Output $manifest
