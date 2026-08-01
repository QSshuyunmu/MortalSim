param(
    [string]$ReleaseDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'release')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$release = [IO.Path]::GetFullPath($ReleaseDirectory)
$liteChecksums = Join-Path $release 'SHA256SUMS-Lite.txt'
$checksumFiles = if (Test-Path $liteChecksums) {
    @($liteChecksums)
} else {
    @((Join-Path $release 'SHA256SUMS.txt')) | Where-Object { Test-Path $_ }
}
if ($checksumFiles.Count -eq 0) { throw "Missing checksum file in $release" }

$expected = @{}
foreach ($checksumFile in $checksumFiles) {
    Get-Content -LiteralPath $checksumFile | Where-Object { $_.Trim() } | ForEach-Object {
        if ($_ -notmatch '^([A-Fa-f0-9]{64})\s{2}(.+)$') { throw "Invalid checksum line: $_" }
        $expected[$Matches[2]] = $Matches[1].ToLowerInvariant()
    }
}

$archives = @($expected.Keys | ForEach-Object {
    $path = Join-Path $release $_
    if (Test-Path -LiteralPath $path) { Get-Item -LiteralPath $path }
})
if ($archives.Count -lt 1) { throw 'No MortalSim Windows archive found.' }
foreach ($archive in $archives) {
    if ($archive.Length -ge 2GB) { throw "GitHub Release asset is too large: $($archive.Name)" }
    if (-not $expected.ContainsKey($archive.Name)) { throw "Archive is absent from SHA256SUMS.txt: $($archive.Name)" }
    $actual = (Get-FileHash -LiteralPath $archive.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected[$archive.Name]) { throw "Checksum mismatch: $($archive.Name)" }
    $archiveZip = [IO.Compression.ZipFile]::OpenRead($archive.FullName)
    try {
        $unpackedBytes = ($archiveZip.Entries | Measure-Object Length -Sum).Sum
        if ($archive.Name -match '-Lite-v' -and $unpackedBytes -gt 700MB) {
            throw "Lite archive exceeds the 700 MiB unpacked budget: $($archive.Name)"
        }
        foreach ($entry in $archiveZip.Entries) {
            $entryName = $entry.FullName -replace '^\./', ''
            if ($entryName -match '\.(pth|onnx|log|pyc)$' -or $entryName -match '(^|/)(__pycache__|models\.json)(/|$)') {
                throw "Forbidden private or generated file in $($archive.Name): $entryName"
            }
            if ($archive.Name -match '-Lite-v' -and $entryName -match '(^|/)(torch|torchvision|torchaudio|onnxruntime)(/|$)') {
                throw "Heavy runtime leaked into Lite archive: $entryName"
            }
            $ownedText = $entryName -notmatch '^_internal/' -or $entryName -match '^_internal/(apps|simulator|mortal|models)/'
            if ($ownedText -and $entry.Length -le 10MB -and $entryName -match '\.(svg|md|txt|json|html|css|js|py|ps1|cmd|toml|ya?ml)$') {
                $reader = [IO.StreamReader]::new($entry.Open())
                try { $content = $reader.ReadToEnd() } finally { $reader.Dispose() }
                if ($content -match '[A-Za-z]:\\(Users|tenhoulib)\\') {
                    throw "Absolute personal path in $($archive.Name): $entryName"
                }
                if ($content -match '(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,})') {
                    throw "Token-like secret in $($archive.Name): $entryName"
                }
            }
        }
    } finally {
        $archiveZip.Dispose()
    }
}

$lite = @($archives | Where-Object { $_.Name -match '-Lite-v' })
$core = @($archives | Where-Object { $_.Name -match '-Core-v' })
if ($lite.Count -eq $archives.Count) {
    if ($lite.Count -ne 1) { throw 'Expected exactly one Lite archive.' }
    $zip = [IO.Compression.ZipFile]::OpenRead($lite[0].FullName)
} elseif ($core.Count -ne 1) {
    throw 'Expected exactly one Core archive.'
} else {
    $zip = [IO.Compression.ZipFile]::OpenRead($core[0].FullName)
}
try {
    $names = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $zip.Entries | ForEach-Object { $names.Add(($_.FullName -replace '^\./', '')) | Out-Null }
    $requiredFiles = if ($lite.Count -eq $archives.Count) {
        @(
            'RELEASE_MANIFEST.json', 'SBOM.cdx.json', 'Start-MortalSim.cmd', 'Install-MortalSim.ps1',
            'legal/LICENSE', 'legal/NOTICE', 'legal/THIRD_PARTY_LICENSES.md', 'legal/MODEL_LICENSE.md',
            '_internal/lite_runtime/mortal_lite_runtime.dll', '_internal/lite_runtime/aoti_cuda_shims.dll',
            '_internal/lite_runtime/cudart64_12.dll', '_internal/lite_runtime/model.dll',
            '_internal/lite_runtime/runtime_manifest.json'
        )
    } else {
        @('RELEASE_MANIFEST.json', 'SBOM.cdx.json', 'Start-MortalSim.cmd', 'Install-MortalSim.ps1', 'legal/LICENSE', 'legal/NOTICE', 'legal/THIRD_PARTY_LICENSES.md', 'legal/MODEL_LICENSE.md', 'legal/MODEL_PROVENANCE.md')
    }
    foreach ($required in $requiredFiles) {
        if (-not $names.Contains($required)) { throw "Core archive is missing $required" }
    }
    $entry = $zip.Entries | Where-Object { ($_.FullName -replace '^\./', '') -eq 'RELEASE_MANIFEST.json' } | Select-Object -First 1
    if (-not $entry) { throw 'Archive is missing RELEASE_MANIFEST.json' }
    $reader = [IO.StreamReader]::new($entry.Open())
    try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
} finally {
    $zip.Dispose()
}

if ($lite.Count -eq $archives.Count) {
    if ($manifest.model_included -ne $false) { throw 'Lite manifest must declare model_included=false.' }
    if ($manifest.decision_contract -ne 'stable_advantage_v2') { throw 'Lite manifest has the wrong decision contract.' }
    $zip = [IO.Compression.ZipFile]::OpenRead($lite[0].FullName)
    try {
        $runtimeEntry = $zip.Entries | Where-Object { ($_.FullName -replace '^\./', '') -eq '_internal/lite_runtime/runtime_manifest.json' } | Select-Object -First 1
        $reader = [IO.StreamReader]::new($runtimeEntry.Open())
        try { $runtimeManifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($runtimeManifest.decision_contract -ne 'stable_advantage_v2' -or $runtimeManifest.compute_capability -ne '8.9' -or $runtimeManifest.batch_size -ne 1000 -or $runtimeManifest.batch_capacity -ne 1024) {
            throw 'Formal Lite runtime manifest contract is invalid.'
        }
    } finally {
        $zip.Dispose()
    }
} elseif ($manifest.model.included -ne $false) {
    throw 'Release manifest must declare model.included=false.'
}

foreach ($component in @($manifest.runtime_components)) {
    if (-not $component -or -not $component.name) { continue }
    if (-not $expected.ContainsKey($component.name)) { throw "Runtime component absent from SHA256SUMS.txt: $($component.name)" }
    if (-not (Test-Path (Join-Path $release $component.name))) { throw "Runtime component missing: $($component.name)" }
}

$modelIncluded = if ($lite.Count -eq $archives.Count) { $manifest.model_included } else { $manifest.model.included }
Write-Host "Release verification passed: $($archives.Count) archives, model included=$modelIncluded."
