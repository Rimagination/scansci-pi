[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$TargetPath,
    [string]$Workspace = "workspace.sqlite",
    [string]$EvidenceDb = "html-papers\evidence.sqlite",
    [string]$Name = "ScanSci",
    [string]$UpdateManifestUrl = "",
    [switch]$Force
)

$target = [System.IO.Path]::GetFullPath($TargetPath)
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw "Desktop executable was not found: $target"
}
$workspacePath = [System.IO.Path]::GetFullPath($Workspace)
$evidencePath = [System.IO.Path]::GetFullPath($EvidenceDb)
$programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
$shortcutPath = Join-Path $programs "$Name.lnk"
if ((Test-Path -LiteralPath $shortcutPath) -and -not $Force) {
    throw "Shortcut already exists: $shortcutPath. Re-run with -Force to replace it."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcutArguments = "--workspace `"$workspacePath`" --evidence-db `"$evidencePath`""
if ($UpdateManifestUrl) {
    $shortcutArguments += " --update-manifest-url `"$UpdateManifestUrl`""
}
$shortcut.Arguments = $shortcutArguments
$shortcut.WorkingDirectory = Split-Path -Parent $workspacePath
$shortcut.IconLocation = "$target,0"
$shortcut.Description = "ScanSci evidence workbench"
$shortcut.Save()
Write-Output $shortcutPath
