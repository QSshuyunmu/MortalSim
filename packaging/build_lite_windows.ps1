param(
    [switch]$SkipBuild,
    [string]$ArtifactDir = $env:MORTALSIM_LITE_ARTIFACT_DIR
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($ArtifactDir)) {
    $ArtifactDir = Join-Path $root "packaging\lite_runtime"
}
$ArtifactDir = [IO.Path]::GetFullPath($ArtifactDir)
$required = @("mortal_lite_runtime.dll", "aoti_cuda_shims.dll", "cudart64_12.dll", "model.dll")
foreach ($name in $required) {
    if (-not (Test-Path (Join-Path $ArtifactDir $name))) {
        throw "Lite runtime artifact is missing: $(Join-Path $ArtifactDir $name). Build the AOTInductor CUDA graph first and set MORTALSIM_LITE_ARTIFACT_DIR."
    }
}

if (-not $SkipBuild) {
    $python = if ($env:PYO3_PYTHON) { $env:PYO3_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
    Write-Host "Building web frontend..."
    Push-Location apps/web
    npm ci
    npm run build
    Pop-Location

    Write-Host "Building libriichi release extension..."
    cargo build --release --lib -p libriichi
    $releasePyd = Join-Path $root "target/release/libriichi.cp313-win_amd64.pyd"
    $releaseDll = Join-Path $root "target/release/libriichi.dll"
    if (Test-Path $releaseDll) { Copy-Item $releaseDll $releasePyd -Force }

    Write-Host "Building libtorch-free MortalSim Lite directory..."
    & $python -m PyInstaller --clean --noconfirm packaging/mortalsim_lite.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
}

$dist = Join-Path $root "dist/MortalSim"
if (-not (Test-Path (Join-Path $dist "MortalSim.exe"))) {
    throw "Portable directory not found at $dist. Run without -SkipBuild first."
}
$runtime = Join-Path $dist "_internal/lite_runtime"
New-Item -ItemType Directory -Force $runtime | Out-Null
foreach ($name in $required) {
    Copy-Item -LiteralPath (Join-Path $ArtifactDir $name) -Destination (Join-Path $runtime $name) -Force
}
# Keep the model name discoverable by the launcher.  AOTInductor commonly
# emits a .wrapper.pyd suffix although it is a native DLL; the alias avoids
# making the portable package depend on the build machine's filename.
Copy-Item -LiteralPath (Join-Path $ArtifactDir "model.dll") -Destination (Join-Path $runtime "mortal-v4-amp-b1024.wrapper.pyd") -Force

$version = (Get-Content pyproject.toml | Select-String '^version =').ToString().Split('"')[1]
$stage = Join-Path $root "build/lite-stage"
$releaseDir = Join-Path $root "release"
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction Ignore
New-Item -ItemType Directory -Force $stage, $releaseDir | Out-Null
Get-ChildItem -LiteralPath $dist -Recurse -File | ForEach-Object {
    $relative = $_.FullName.Substring($dist.Length).TrimStart('\', '/')
    if ($relative -notmatch '\.(pth|onnx)$') {
        $destination = Join-Path $stage $relative
        New-Item -ItemType Directory -Force (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }
}
foreach ($file in @("LICENSE", "NOTICE", "THIRD_PARTY_LICENSES.md", "MODEL_LICENSE.md")) {
    New-Item -ItemType Directory -Force (Join-Path $stage "legal") | Out-Null
    Copy-Item (Join-Path $root $file) (Join-Path $stage "legal") -Force
}
foreach ($file in @("INSTALL.md", "USER_GUIDE.md", "TROUBLESHOOTING.md", "SMOKE_TEST.md", "LITE_VALIDATION.md")) {
    New-Item -ItemType Directory -Force (Join-Path $stage "docs") | Out-Null
    Copy-Item (Join-Path $root "docs\$file") (Join-Path $stage "docs") -Force
}
@{ 
    product = "MortalSim"
    variant = "Lite"
    version = $version
    model_included = $false
    runtime = "AOTInductor CUDA; import a compatible v4 .pth in the app"
    files = @($required)
} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $stage "RELEASE_MANIFEST.json") -Encoding utf8

# Keep the portable package self-describing without pulling a package manager
# or the build machine's full dependency tree into the archive.
$components = @(
    [ordered]@{ type = "application"; name = "MortalSim"; version = $version },
    [ordered]@{ type = "library"; name = "libriichi"; version = "workspace" },
    [ordered]@{ type = "library"; name = "numpy"; version = "2.3.5" },
    [ordered]@{ type = "library"; name = "fastapi"; version = "0.137.1" },
    [ordered]@{ type = "library"; name = "uvicorn"; version = "0.46.0" },
    [ordered]@{ type = "library"; name = "pydantic"; version = "2.13.3" },
    [ordered]@{ type = "library"; name = "openpyxl"; version = "3.1.5" },
    [ordered]@{ type = "library"; name = "AOTInductor CUDA runtime"; version = "PyTorch 2.13 build" },
    [ordered]@{ type = "library"; name = "CUDA runtime"; version = "12.x" }
)
[ordered]@{
    bomFormat = "CycloneDX"
    specVersion = "1.5"
    version = 1
    metadata = [ordered]@{ timestamp = [DateTime]::UtcNow.ToString("o"); component = [ordered]@{ type = "application"; name = "MortalSim"; version = $version } }
    components = $components
} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $stage "SBOM.cdx.json") -Encoding utf8

foreach ($file in @("Start-MortalSim.cmd", "Install-MortalSim.ps1")) {
    Copy-Item (Join-Path $root "packaging\$file") $stage -Force
}

$archive = Join-Path $releaseDir "MortalSim-Windows-x64-Lite-v$version.zip"
Remove-Item $archive -Force -ErrorAction Ignore
# Windows 10/11 ships bsdtar.  It produces the same ZIP format as
# Compress-Archive but is substantially faster for the many small PyInstaller
# files in the portable directory and avoids holding the whole archive in the
# PowerShell process.
tar -a -c -f $archive -C $stage .
$hash = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $(Split-Path $archive -Leaf)" | Set-Content (Join-Path $releaseDir "SHA256SUMS-Lite.txt") -Encoding ascii
$bytes = (Get-Item $archive).Length
Write-Host ("Lite archive: {0:N1} MiB ({1})" -f ($bytes / 1MB), $archive)
if ($bytes -gt 300MB) { throw "Lite archive exceeds the 300 MiB release budget." }
