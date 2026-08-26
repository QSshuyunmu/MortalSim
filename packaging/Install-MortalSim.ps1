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

$exePath = Join-Path $root "MortalSim.exe"
$launcherPath = Join-Path $root "Start-MortalSim.cmd"
$iconPath = Join-Path $root "MortalSim.ico"
$shortcutTargets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "MortalSim.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\MortalSim.lnk")
)

function New-MortalSimShortcut([string]$shortcutPath) {
    $directory = Split-Path -Parent $shortcutPath
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = if (Test-Path $launcherPath) { $launcherPath } else { $exePath }
    $shortcut.WorkingDirectory = $root
    $shortcut.IconLocation = if (Test-Path $iconPath) { "$iconPath,0" } else { "$exePath,0" }
    $shortcut.Description = "MortalSim 本地日麻第一打模拟器"
    $shortcut.Save()
}

foreach ($shortcutPath in $shortcutTargets) {
    New-MortalSimShortcut $shortcutPath
}
Write-Host "Shortcuts created on the Desktop and in the Start menu." -ForegroundColor Green

if (-not $NoLaunch) {
    Start-Process -FilePath $exePath
}
