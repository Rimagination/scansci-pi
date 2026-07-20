[CmdletBinding()]
param(
    [string]$GatewayDirectory = "",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $GatewayDirectory) {
    $GatewayDirectory = Join-Path (Split-Path -Parent $scriptDirectory) "services\scansci-glm-gateway"
}
if (-not (Test-Path -LiteralPath $GatewayDirectory -PathType Container)) {
    throw "ScanSci gateway directory was not found: $GatewayDirectory"
}
if ($ValidateOnly) {
    Write-Output "ScanSci SiliconFlow gateway setup is ready: $GatewayDirectory"
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "ScanSciAI SiliconFlow gateway secret"
$form.Size = New-Object System.Drawing.Size(530, 185)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$label = New-Object System.Windows.Forms.Label
$label.AutoSize = $true
$label.Location = New-Object System.Drawing.Point(20, 20)
$label.Text = "Enter the SiliconFlow API key for the ScanSciAI public gateway."
$form.Controls.Add($label)

$apiKeyBox = New-Object System.Windows.Forms.TextBox
$apiKeyBox.Location = New-Object System.Drawing.Point(20, 52)
$apiKeyBox.Size = New-Object System.Drawing.Size(465, 24)
$apiKeyBox.UseSystemPasswordChar = $true
$form.Controls.Add($apiKeyBox)

$save = New-Object System.Windows.Forms.Button
$save.Text = "Store in Cloudflare"
$save.Location = New-Object System.Drawing.Point(305, 94)
$save.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $save
$form.Controls.Add($save)

$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = "Cancel"
$cancel.Location = New-Object System.Drawing.Point(410, 94)
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.CancelButton = $cancel
$form.Controls.Add($cancel)

if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    exit 1
}

$apiKey = $apiKeyBox.Text.Trim()
$apiKeyBox.Clear()
$form.Dispose()
if (-not $apiKey) {
    throw "An API key is required."
}

Push-Location $GatewayDirectory
try {
    $apiKey | & npx wrangler secret put SILICONFLOW_API_KEY
    if ($LASTEXITCODE -ne 0) {
        throw "Cloudflare rejected the SiliconFlow gateway secret."
    }
}
finally {
    Pop-Location
    $apiKey = $null
    [GC]::Collect()
}

[System.Windows.Forms.MessageBox]::Show(
    "The SiliconFlow upstream key is now stored as a Cloudflare Worker Secret. It is not included in ScanSci or this repository.",
    "ScanSciAI gateway",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
