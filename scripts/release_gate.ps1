[CmdletBinding()]
param(
    [ValidateSet("targeted", "source", "beta", "release")]
    [string]$Profile = "release",
    [string]$Contract = "config\release-gate.json",
    [string]$Scope = "",
    [string]$KnowledgeSource = "",
    [string]$OutputRoot = "",
    [string]$BuildId = "",
    [string]$ResumeReport = "",
    [string]$PromoteReport = "",
    [string]$VisualEvidenceDir = "",
    [switch]$PlanOnly
)

$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$gateScript = Join-Path $PSScriptRoot "release_gate.py"
$arguments = @(
    $gateScript,
    "--profile", $Profile,
    "--contract", $Contract
)
if ($Scope) {
    $arguments += @("--scope", $Scope)
}
if ($KnowledgeSource) {
    $arguments += @("--knowledge-source", $KnowledgeSource)
}
if ($OutputRoot) {
    $arguments += @("--output-root", $OutputRoot)
}
if ($BuildId) {
    $arguments += @("--build-id", $BuildId)
}
if ($ResumeReport) {
    $arguments += @("--resume-report", $ResumeReport)
}
if ($PromoteReport) {
    $arguments += @("--promote-report", $PromoteReport)
}
if ($VisualEvidenceDir) {
    $arguments += @("--visual-evidence-dir", $VisualEvidenceDir)
}
if ($PlanOnly) {
    $arguments += "--plan-only"
}

& python @arguments
exit $LASTEXITCODE
