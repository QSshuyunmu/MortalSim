param(
    [string]$ReleaseDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'release')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$release = [IO.Path]::GetFullPath($ReleaseDirectory)
$checksumFile = Join-Path $release 'SHA256SUMS.txt'
if (-not (Test-Path $checksumFile)) { throw "Missing checksum file: $checksumFile" }

$expected = @{}
Get-Content -LiteralPath $checksumFile | Where-Object { $_.Trim() } | ForEach-Object {
    if ($_ -notmatch '^([A-Fa-f0-9]{64})\s{2}(.+)$') { throw "Invalid checksum line: $_" }
    $expected[$Matches[2]] = $Matches[1].ToLowerInvariant()
}

$archives = Get-ChildItem -LiteralPath $release -Filter 'MortalSim-Windows-x64-CUDA-*-v*.zip' -File
if ($archives.Count -lt 2) { throw 'Expected one Core archive and at least one CUDA Runtime archive.' }
foreach ($archive in $archives) {
    if ($archive.Length -ge 2GB) { throw "GitHub Release asset is too large: $($archive.Name)" }
    if (-not $expected.ContainsKey($archive.Name)) { throw "Archive is absent from SHA256SUMS.txt: $($archive.Name)" }
    $actual = (Get-FileHash -LiteralPath $archive.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected[$archive.Name]) { throw "Checksum mismatch: $($archive.Name)" }
    $archiveZip = [IO.Compression.ZipFile]::OpenRead($archive.FullName)
    try {
        foreach ($entry in $archiveZip.Entries) {
            if ($entry.FullName -match '\.(pth|onnx|log|pyc)$' -or $entry.FullName -match '(^|/)(__pycache__|models\.json)(/|$)') {
                throw "Forbidden private or generated file in $($archive.Name): $($entry.FullName)"
            }
            $ownedText = $entry.FullName -notmatch '^_internal/' -or $entry.FullName -match '^_internal/(apps|simulator|mortal|models)/'
            if ($ownedText -and $entry.Length -le 10MB -and $entry.FullName -match '\.(svg|md|txt|json|html|css|js|py|ps1|cmd|toml|ya?ml)$') {
                $reader = [IO.StreamReader]::new($entry.Open())
                try { $content = $reader.ReadToEnd() } finally { $reader.Dispose() }
                if ($content -match '[A-Za-z]:\\(Users|tenhoulib)\\') {
                    throw "Absolute personal path in $($archive.Name): $($entry.FullName)"
                }
                if ($content -match '(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,})') {
                    throw "Token-like secret in $($archive.Name): $($entry.FullName)"
                }
            }
        }
    } finally {
        $archiveZip.Dispose()
    }
}

$core = @($archives | Where-Object { $_.Name -match '-Core-v' })
if ($core.Count -ne 1) { throw 'Expected exactly one Core archive.' }
$zip = [IO.Compression.ZipFile]::OpenRead($core[0].FullName)
try {
    $names = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $zip.Entries | ForEach-Object { $names.Add($_.FullName) | Out-Null }
    foreach ($required in 'RELEASE_MANIFEST.json', 'SBOM.cdx.json', 'Start-MortalSim.cmd', 'Install-MortalSim.ps1', 'legal/LICENSE', 'legal/NOTICE', 'legal/THIRD_PARTY_LICENSES.md', 'legal/MODEL_LICENSE.md', 'legal/MODEL_PROVENANCE.md') {
        if (-not $names.Contains($required)) { throw "Core archive is missing $required" }
    }
    $entry = $zip.GetEntry('RELEASE_MANIFEST.json')
    $reader = [IO.StreamReader]::new($entry.Open())
    try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
} finally {
    $zip.Dispose()
}

if ($manifest.model.included -ne $false) {
    throw 'Release manifest must declare model.included=false.'
}

foreach ($component in @($manifest.runtime_components)) {
    if (-not $expected.ContainsKey($component.name)) { throw "Runtime component absent from SHA256SUMS.txt: $($component.name)" }
    if (-not (Test-Path (Join-Path $release $component.name))) { throw "Runtime component missing: $($component.name)" }
}

Write-Host "Release verification passed: $($archives.Count) archives, model included=$($manifest.model.included)."
