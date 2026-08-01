param(
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
$manifestPath = Join-Path $root "RELEASE_MANIFEST.json"

if (-not (Test-Path $manifestPath)) {
    throw "RELEASE_MANIFEST.json is missing. Fully extract the MortalSim Lite ZIP before running."
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$requiredFiles = if ($manifest.required_files) { @($manifest.required_files) } elseif ($manifest.files) { @($manifest.files | ForEach-Object { "_internal/lite_runtime/$_" }) } else { @("MortalSim.exe") }
$missing = @()
foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path (Join-Path $root $relativePath))) {
        $missing += $relativePath
    }
}

if ($missing.Count -gt 0) {
    $sample = ($missing | Select-Object -First 5) -join "`n  - "
    throw "MortalSim Lite is incomplete. Download the ZIP again and fully extract it before starting.`nMissing:`n  - $sample"
}

if (($manifest.model.included -ne $true) -and ($manifest.model_included -ne $true)) {
    Write-Host "This package contains no model checkpoint. Import a compatible local .pth file from Settings after MortalSim opens." -ForegroundColor Yellow
}

if (-not $NoLaunch) {
    Start-Process -FilePath (Join-Path $root "MortalSim.exe")
}
