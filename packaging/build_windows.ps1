param(
    [ValidateSet("CUDA")]
    [string]$Variant = "CUDA",
    [switch]$SkipBuild,
    [ValidateRange(512, 1900)]
    [int]$RuntimePartMiB = 1536
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-ReleaseVersion {
    $pep440 = (Get-Content pyproject.toml | Select-String '^version =').ToString().Split('"')[1]
    if ($pep440 -match '^(?<base>\d+\.\d+\.\d+)a(?<number>\d+)$') {
        return "$($Matches.base)-alpha.$($Matches.number)"
    }
    return $pep440
}

function Get-RelativeReleasePath([string]$Base, [string]$Path) {
    $basePath = [IO.Path]::GetFullPath($Base).TrimEnd('\', '/') + '\'
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($basePath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the release root: $Path"
    }
    return $fullPath.Substring($basePath.Length).Replace('\', '/')
}

function New-HardLinkOrCopy([string]$Source, [string]$Destination) {
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force $parent | Out-Null
    try {
        New-Item -ItemType HardLink -Path $Destination -Target $Source -ErrorAction Stop | Out-Null
    } catch {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

function New-ReleaseArchive([string]$Root, [System.IO.FileInfo[]]$Files, [string]$ArchivePath) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction Ignore
    $stream = [IO.File]::Open($ArchivePath, [IO.FileMode]::CreateNew)
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        foreach ($file in $Files) {
            $entryName = Get-RelativeReleasePath $Root $file.FullName
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip,
                $file.FullName,
                $entryName,
                [IO.Compression.CompressionLevel]::Fastest
            ) | Out-Null
        }
    } finally {
        $zip.Dispose()
        $stream.Dispose()
    }
}

function Copy-ReleaseSupport([string]$Stage) {
    Copy-Item -LiteralPath (Join-Path $root 'packaging\Install-MortalSim.ps1') -Destination (Join-Path $Stage 'Install-MortalSim.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $root 'packaging\Start-MortalSim.cmd') -Destination (Join-Path $Stage 'Start-MortalSim.cmd') -Force

    $legal = Join-Path $Stage 'legal'
    New-Item -ItemType Directory -Force $legal | Out-Null
    foreach ($file in 'LICENSE', 'NOTICE', 'THIRD_PARTY_LICENSES.md', 'MODEL_LICENSE.md') {
        Copy-Item -LiteralPath (Join-Path $root $file) -Destination $legal -Force
    }
    foreach ($file in 'INSTALL.md', 'USER_GUIDE.md', 'TROUBLESHOOTING.md') {
        Copy-Item -LiteralPath (Join-Path $root "docs\$file") -Destination $legal -Force
    }
    Copy-Item -LiteralPath (Join-Path $root 'models\MODEL_MANIFEST.json') -Destination $legal -Force
    Copy-Item -LiteralPath (Join-Path $root 'models\MODEL_PROVENANCE.md') -Destination $legal -Force
}

function New-ReleaseSbom([string]$Stage, [string]$Version) {
    $components = [System.Collections.Generic.List[object]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    function Add-SbomComponent([string]$Ecosystem, [string]$Name, [string]$ComponentVersion, [string]$Type = 'library') {
        if ([string]::IsNullOrWhiteSpace($Name) -or [string]::IsNullOrWhiteSpace($ComponentVersion)) { return }
        $key = "$Ecosystem|$Name|$ComponentVersion"
        if ($seen.Add($key)) {
            $components.Add([ordered]@{
                type = $Type
                name = $Name
                version = $ComponentVersion
                purl = "pkg:$Ecosystem/$Name@$ComponentVersion"
            })
        }
    }

    Add-SbomComponent 'generic' 'MortalSim' $Version 'application'
    $internal = Join-Path $Stage '_internal'
    Get-ChildItem -LiteralPath $internal -Recurse -Directory -Filter '*.dist-info' -ErrorAction SilentlyContinue | ForEach-Object {
        $metadata = Join-Path $_.FullName 'METADATA'
        if (Test-Path $metadata) {
            $lines = Get-Content -LiteralPath $metadata -TotalCount 40
            $name = (($lines | Where-Object { $_ -like 'Name:*' } | Select-Object -First 1) -replace '^Name:\s*', '')
            $componentVersion = (($lines | Where-Object { $_ -like 'Version:*' } | Select-Object -First 1) -replace '^Version:\s*', '')
            Add-SbomComponent 'pypi' $name $componentVersion
        }
    }

    $packageLock = Join-Path $root 'apps\web\package-lock.json'
    if (Test-Path $packageLock) {
        $nodeScript = "const p=require('./apps/web/package-lock.json').packages; for (const [k,v] of Object.entries(p)) { const n=v.name || (k.startsWith('node_modules/') ? k.slice(13) : ''); if (n && v.version) console.log(n + '\t' + v.version); }"
        foreach ($line in (node -e $nodeScript)) {
            $parts = $line -split "`t", 2
            if ($parts.Count -eq 2) {
                Add-SbomComponent 'npm' $parts[0] $parts[1]
            }
        }
    }

    $cargo = cargo metadata --locked --format-version 1 | ConvertFrom-Json
    foreach ($package in $cargo.packages) {
        Add-SbomComponent 'cargo' ([string]$package.name) ([string]$package.version)
    }

    $bom = [ordered]@{
        bomFormat = 'CycloneDX'
        specVersion = '1.5'
        version = 1
        metadata = [ordered]@{
            timestamp = [DateTime]::UtcNow.ToString('o')
            component = [ordered]@{ type = 'application'; name = 'MortalSim'; version = $Version }
            properties = @([ordered]@{ name = 'mortal-sim:scope'; value = 'packaged-python-runtime-plus-source-dependencies' })
        }
        components = @($components | Sort-Object purl)
    }
    $bom | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Stage 'SBOM.cdx.json') -Encoding utf8
}

function Split-RuntimeFiles([System.IO.FileInfo[]]$Files, [int64]$LimitBytes) {
    $groups = [System.Collections.Generic.List[object]]::new()
    $current = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
    [int64]$currentBytes = 0
    $orderedFiles = $Files | Sort-Object -Property @{ Expression = { $_.Length }; Descending = $true }, @{ Expression = { $_.FullName }; Descending = $false }
    foreach ($file in $orderedFiles) {
        if ($current.Count -gt 0 -and ($currentBytes + $file.Length) -gt $LimitBytes) {
            $groups.Add(@($current.ToArray()))
            $current = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
            $currentBytes = 0
        }
        $current.Add($file)
        $currentBytes += $file.Length
    }
    if ($current.Count -gt 0) {
        $groups.Add(@($current.ToArray()))
    }
    return @($groups)
}

if (-not $SkipBuild) {
    if (-not $env:PYO3_PYTHON) {
        $python = Get-Command python -ErrorAction Stop
        $env:PYO3_PYTHON = $python.Source
    }
    Write-Host "Using Python: $env:PYO3_PYTHON"
    $cudaProbe = & $env:PYO3_PYTHON -c "import sys,torch; print(f'PyTorch {torch.__version__}, CUDA {torch.version.cuda}'); sys.exit(0 if torch.version.cuda else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw 'CUDA build requires CUDA-enabled PyTorch. Install requirements-lock.txt first. A GPU is required at runtime, not on the build host.'
    }

    $env:MORTALSIM_INCLUDE_MODEL = '0'
    Write-Host 'Building web frontend...'
    Push-Location apps/web
    npm ci
    npm run build
    Pop-Location

    Write-Host 'Building libriichi release extension...'
    cargo build --release --lib -p libriichi
    $releasePyd = Join-Path $root 'target/release/libriichi.cp313-win_amd64.pyd'
    $releaseDll = Join-Path $root 'target/release/libriichi.dll'
    if (Test-Path $releaseDll) {
        Copy-Item $releaseDll $releasePyd -Force
    }

    Write-Host 'Building MortalSim Portable directory...'
    & $env:PYO3_PYTHON -m PyInstaller --clean --noconfirm packaging/mortalsim.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
}

$dist = Join-Path $root 'dist/MortalSim'
if (-not (Test-Path (Join-Path $dist 'MortalSim.exe'))) {
    throw "Portable directory not found at $dist. Run without -SkipBuild first."
}

$version = Get-ReleaseVersion
$releaseDir = Join-Path $root 'release'
$stage = Join-Path $root 'build/release-stage'
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction Ignore
New-Item -ItemType Directory -Force $stage, $releaseDir | Out-Null

Write-Host 'Preparing a model-safe release stage...'
Get-ChildItem -LiteralPath $dist -Recurse -File | ForEach-Object {
    $relative = Get-RelativeReleasePath $dist $_.FullName
    if ($relative -ne '_internal/Akagi/model_v4_20240308_best_min.pth') {
        New-HardLinkOrCopy $_.FullName (Join-Path $stage $relative)
    }
}
Copy-ReleaseSupport $stage
New-ReleaseSbom $stage $version

$runtimeFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $stage '_internal/torch/lib') -File -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath (Join-Path $stage '_internal/torch/bin') -File -ErrorAction SilentlyContinue
)
if ($runtimeFiles.Count -eq 0) {
    throw 'No PyTorch CUDA runtime files were found in the portable stage.'
}

$runtimeGroups = Split-RuntimeFiles $runtimeFiles ([int64]$RuntimePartMiB * 1MB)
$runtimeComponents = @()
for ($index = 0; $index -lt $runtimeGroups.Count; $index++) {
    $name = "MortalSim-Windows-x64-$Variant-Runtime-{0:D2}-v$version.zip" -f ($index + 1)
    $path = Join-Path $releaseDir $name
    Write-Host "Writing runtime archive $($index + 1)/$($runtimeGroups.Count)..."
    New-ReleaseArchive $stage $runtimeGroups[$index] $path
    $runtimeComponents += [ordered]@{
        name = $name
        sha256 = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
        size_bytes = (Get-Item $path).Length
        files = @($runtimeGroups[$index] | ForEach-Object { Get-RelativeReleasePath $stage $_.FullName })
    }
}

$manifest = [ordered]@{
    schema_version = 1
    product = 'MortalSim'
    version = $version
    variant = $Variant
    layout = 'core-plus-cuda-runtime'
    model = [ordered]@{
        included = $false
        id = $null
        sha256 = $null
        status = 'not-included-user-provided-model-required'
    }
    runtime_components = $runtimeComponents
    required_files = @($runtimeFiles | ForEach-Object { Get-RelativeReleasePath $stage $_.FullName })
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stage 'RELEASE_MANIFEST.json') -Encoding utf8

$runtimeSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$runtimeFiles | ForEach-Object { $runtimeSet.Add($_.FullName) | Out-Null }
$coreFiles = @(Get-ChildItem -LiteralPath $stage -Recurse -File | Where-Object { -not $runtimeSet.Contains($_.FullName) })
$coreName = "MortalSim-Windows-x64-$Variant-Core-v$version.zip"
$corePath = Join-Path $releaseDir $coreName
Write-Host 'Writing Core archive...'
New-ReleaseArchive $stage $coreFiles $corePath

$allComponents = @([ordered]@{
    name = $coreName
    sha256 = (Get-FileHash $corePath -Algorithm SHA256).Hash.ToLowerInvariant()
    size_bytes = (Get-Item $corePath).Length
}) + $runtimeComponents
$allComponents | ForEach-Object { "$($_.sha256.ToUpperInvariant())  $($_.name)" } | Set-Content -LiteralPath (Join-Path $releaseDir 'SHA256SUMS.txt') -Encoding ascii

Write-Host "Created $($allComponents.Count) GitHub-compatible release archives:"
$allComponents | ForEach-Object { Write-Host "  $($_.name) ($([math]::Round($_.size_bytes / 1GB, 2)) GiB)" }
