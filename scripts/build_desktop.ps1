[CmdletBinding()]
param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onedir",
    [string]$OutputDir = "",
    [string]$Name = "ScanSci",
    [switch]$IncludeLocalModels
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputDir) {
    $OutputDir = Join-Path $projectRoot "dist"
}
$entryPoint = Join-Path $projectRoot "scripts\scansci_desktop_entry.py"
$assetSource = Join-Path $projectRoot "src\scansci_html\web"
$skillAssetSource = Join-Path $projectRoot "src\scansci_html\builtin_skill_assets"
$iconPath = Join-Path $assetSource "scansci.ico"
$buildPath = Join-Path $projectRoot "build\desktop"
$specPath = Join-Path $projectRoot "build\desktop-spec"
$metadataPath = Join-Path $projectRoot "build\release-metadata"
$buildInfoPath = Join-Path $metadataPath "build-info.json"
$piBundle = Join-Path $projectRoot "pi-runtime\dist\main.mjs"
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand) {
    throw "Node.js 22 or newer is required to build the ScanSci Pi runtime."
}
$nodeExe = $nodeCommand.Source

& npm --prefix $projectRoot run build:pi-runtime
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not (Test-Path -LiteralPath $piBundle -PathType Leaf)) {
    throw "ScanSci Pi sidecar bundle was not generated: $piBundle"
}

New-Item -ItemType Directory -Force -Path $metadataPath | Out-Null
$commit = ""
try {
    $commit = (& git -C $projectRoot rev-parse --short HEAD 2>$null).Trim()
} catch {
    $commit = ""
}
$buildInfo = [ordered]@{
    version = "0.2.0"
    build_id = "$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    built_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    commit = $commit
}
$buildInfo | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $buildInfoPath -Encoding utf8

if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "ScanSci Windows icon was not found: $iconPath. Run scripts\build_windows_icon.py first."
}

$pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $Name,
    "--icon", $iconPath,
    "--$Mode",
    "--paths", (Join-Path $projectRoot "src"),
    "--add-data", "$assetSource;scansci_html\web",
    "--add-data", "$skillAssetSource;scansci_html\builtin_skill_assets",
    "--add-data", "$buildInfoPath;scansci_html",
    "--add-data", "$piBundle;pi_runtime",
    "--add-binary", "$nodeExe;pi_runtime",
    # python-pptx loads its default blank deck from package data at runtime;
    # include it explicitly so a packaged ScanSci can create PPTX files.
    "--collect-data", "pptx",
    "--collect-data", "docx",
    "--collect-data", "litellm",
    "--collect-data", "markitdown",
    "--collect-data", "tiktoken",
    "--collect-submodules", "markitdown",
    "--collect-submodules", "litellm.llms.openai",
    "--collect-submodules", "litellm.llms.anthropic",
    "--collect-submodules", "tiktoken_ext",
    "--collect-all", "sqlite_vec",
    "--hidden-import", "litellm",
    "--hidden-import", "tiktoken_ext.openai_public",
    "--hidden-import", "opentelemetry.sdk",
    "--hidden-import", "opentelemetry.sdk.trace",
    "--hidden-import", "pyzotero.zotero",
    "--distpath", $OutputDir,
    "--workpath", $buildPath,
    "--specpath", $specPath,
    $entryPoint
)

if ($IncludeLocalModels) {
    # Optional large local-model runtime. The default MVP build keeps provider
    # models and the Pi tool loop, avoiding several gigabytes of Torch files.
    foreach ($module in @("transformers", "torch", "huggingface_hub", "safetensors")) {
        $pyInstallerArgs += "--collect-all"
        $pyInstallerArgs += $module
    }
}

# The desktop workbench always uses the local lexical retriever.  These are
# optional training, benchmarking, and model-provider stacks which PyInstaller
# discovers through lazy imports in the full ScanSci library.  Leaving them out
# keeps the desktop deliverable practical while the CLI retains those options.
$excludedModules = @(
    "boto3",
    "botocore",
    "cv2",
    "IPython",
    "jupyter",
    "keras",
    "matplotlib",
    "pandas",
    "pygame",
    "pytest",
    "scipy",
    "sentence_transformers",
    "sklearn",
    "tensorflow",
    "torchaudio",
    "torchvision"
)
if (-not $IncludeLocalModels) {
    $excludedModules += @("huggingface_hub", "safetensors", "torch", "transformers")
}
foreach ($module in $excludedModules) {
    $pyInstallerArgs += "--exclude-module"
    $pyInstallerArgs += $module
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$resolvedPackage = (& python -c "from pathlib import Path; import scansci_html; print(Path(scansci_html.__file__).resolve())").Trim()
$expectedSourceRoot = (Resolve-Path (Join-Path $projectRoot "src\scansci_html")).Path
if (-not $resolvedPackage.StartsWith($expectedSourceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Build resolved scansci_html outside this project: $resolvedPackage"
}

& python -m PyInstaller @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
