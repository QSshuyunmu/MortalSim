param(
    [ValidateSet("CUDA")]
    [string]$Variant = "CUDA",
    [switch]$AllowMissingModel
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $env:PYO3_PYTHON) {
    $env:PYO3_PYTHON = (Get-Command python).Source
}
Write-Host "Using Python: $env:PYO3_PYTHON"
$cudaProbe = & $env:PYO3_PYTHON -c "import sys,torch; print(f'PyTorch {torch.__version__}, CUDA {torch.version.cuda}'); sys.exit(0 if torch.version.cuda else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "CUDA build requires CUDA-enabled PyTorch. Install requirements-cuda.txt first. A GPU is required at runtime, not on the build host."
}

$modelPath = Join-Path $root "Akagi/model_v4_20240308_best_min.pth"
if (-not (Test-Path $modelPath) -and -not $AllowMissingModel) {
    throw "Authorized Mortal model is missing at $modelPath. Add it after license review, or pass -AllowMissingModel for a diagnostics-only build."
}

Write-Host "Building web frontend..."
Push-Location apps/web
npm ci
npm run build
Pop-Location

Write-Host "Building libriichi release extension..."
cargo build --release --lib -p libriichi
$releasePyd = Join-Path $root "target/release/libriichi.cp313-win_amd64.pyd"
$releaseDll = Join-Path $root "target/release/libriichi.dll"
if (-not (Test-Path $releasePyd) -and (Test-Path $releaseDll)) {
    Copy-Item $releaseDll $releasePyd -Force
}

Write-Host "Building MortalSim Portable directory..."
& $env:PYO3_PYTHON -m PyInstaller --clean --noconfirm packaging/mortalsim.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$version = (Get-Content pyproject.toml | Select-String '^version =').ToString().Split('"')[1]
$dist = Join-Path $root "dist/MortalSim"
$releaseDir = Join-Path $root "release"
New-Item -ItemType Directory -Force $releaseDir | Out-Null
$archive = Join-Path $releaseDir "MortalSim-Windows-x64-$Variant-v$version.zip"
if (Test-Path $archive) { Remove-Item $archive -Force }
if (Get-Command tar.exe -ErrorAction SilentlyContinue) {
    tar.exe -a -c -f $archive -C $dist .
} else {
    Compress-Archive -Path "$dist/*" -DestinationPath $archive
}
$hash = (Get-FileHash $archive -Algorithm SHA256).Hash
"$hash  $(Split-Path $archive -Leaf)" | Set-Content (Join-Path $releaseDir "SHA256SUMS.txt")
Get-FileHash $archive -Algorithm SHA256 | Format-List
Write-Host "Created $archive"
