param(
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
$manifestPath = Join-Path $root "RELEASE_MANIFEST.json"

if (-not (Test-Path $manifestPath)) {
    throw "RELEASE_MANIFEST.json is missing. Extract the Core archive before running MortalSim."
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$missing = @()
foreach ($relativePath in @($manifest.required_files)) {
    if (-not (Test-Path (Join-Path $root $relativePath))) {
        $missing += $relativePath
    }
}

if ($missing.Count -gt 0) {
    $sample = ($missing | Select-Object -First 5) -join "`n  - "
    throw "MortalSim is incomplete. Extract every Runtime archive into this same folder before starting.`nMissing:`n  - $sample"
}

if ($manifest.model.included -ne $true) {
    Write-Host "This package contains no model checkpoint. Import a compatible local .pth file from Settings after MortalSim opens." -ForegroundColor Yellow
}

if (-not $NoLaunch) {
    Start-Process -FilePath (Join-Path $root "MortalSim.exe")
}
