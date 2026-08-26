param(
    [Parameter(Mandatory)]
    [string]$ModelPath,
    [Parameter(Mandatory)]
    [string]$Destination,
    [string]$PortableArchive,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$model = [System.IO.Path]::GetFullPath($ModelPath)
$destinationPath = [System.IO.Path]::GetFullPath($Destination)

if (-not $PortableArchive) {
    $candidate = Get-ChildItem -LiteralPath $root -Directory -Filter "release-v*" |
        ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File -Filter "MortalSim-Windows-x64-Lite-*.zip" } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "No MortalSim Lite release ZIP was found; pass -PortableArchive explicitly."
    }
    $PortableArchive = $candidate.FullName
}
$archive = [System.IO.Path]::GetFullPath($PortableArchive)

if (-not (Test-Path -LiteralPath $model -PathType Leaf)) {
    throw "Model not found: $model"
}
if (-not $model.EndsWith(".pth", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The local bundle model must be a .pth checkpoint."
}
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw "Portable archive not found: $archive"
}
if ($destinationPath -eq $root -or $root.StartsWith($destinationPath.TrimEnd("\") + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination cannot be the source repository or one of its parents: $destinationPath"
}
if (Test-Path -LiteralPath $destinationPath) {
    if ((Get-ChildItem -LiteralPath $destinationPath -Force | Measure-Object).Count -gt 0) {
        throw "Destination must be absent or empty: $destinationPath"
    }
} else {
    New-Item -ItemType Directory -Path $destinationPath | Out-Null
}

Expand-Archive -LiteralPath $archive -DestinationPath $destinationPath
$required = @("MortalSim.exe", "RELEASE_MANIFEST.json", "_internal")
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $destinationPath $relative))) {
        throw "Portable archive is incomplete; missing $relative"
    }
}

$dataDir = Join-Path $destinationPath "data"
$bundleManifest = Join-Path $destinationPath "LOCAL_BUNDLE_MANIFEST.json"
Push-Location $root
try {
    & $PythonExe "packaging\prepare_local_model.py" `
        --data-dir $dataDir `
        --model $model `
        --archive $archive `
        --output $bundleManifest
    if ($LASTEXITCODE -ne 0) {
        throw "Model validation or local registry creation failed."
    }
} finally {
    Pop-Location
}

$localLauncher = Join-Path $PSScriptRoot "Start-MortalSim-Local.cmd"
Copy-Item -LiteralPath $localLauncher -Destination (Join-Path $destinationPath "Start-MortalSim-Local.cmd") -Force
Copy-Item -LiteralPath $localLauncher -Destination (Join-Path $destinationPath "Start-MortalSim.cmd") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README-LOCAL.txt") -Destination (Join-Path $destinationPath "README-LOCAL.txt") -Force

$bytes = (Get-ChildItem -LiteralPath $destinationPath -Recurse -Force -File | Measure-Object Length -Sum).Sum
$models = Get-ChildItem -LiteralPath (Join-Path $dataDir "models") -File -Filter "*.pth"
if ($models.Count -ne 1) {
    throw "Local bundle must contain exactly one model, found $($models.Count)."
}
Write-Host "Local MortalSim Lite bundle is ready: $destinationPath"
Write-Host ("Size: {0:N2} MiB" -f ($bytes / 1MB))
Write-Host "Launch with Start-MortalSim-Local.cmd. Do not publish this private bundle."
