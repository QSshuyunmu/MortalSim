param(
    [ValidateSet("Cache", "Build", "Package", "All")]
    [string]$Mode = "All",
    [switch]$Apply,
    [switch]$RemovePortable,
    [switch]$RemoveRelease,
    [switch]$PruneRelease
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))

function Resolve-WorkspaceTarget {
    param([Parameter(Mandatory)][string]$RelativePath)

    $target = [System.IO.Path]::GetFullPath((Join-Path $root $RelativePath))
    $prefix = $root.TrimEnd("\") + "\"
    if (-not $target.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside workspace: $target"
    }
    if ($target -eq $root -or $target -eq (Join-Path $root ".git")) {
        throw "Refusing protected path: $target"
    }
    return $target
}

function Get-PathBytes {
    param([Parameter(Mandatory)][string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return 0L
    }
    $item = Get-Item -LiteralPath $LiteralPath -Force
    if (-not $item.PSIsContainer) {
        return [long]$item.Length
    }
    $measure = Get-ChildItem -LiteralPath $LiteralPath -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum
    if ($null -eq $measure.Sum) {
        return 0L
    }
    return [long]$measure.Sum
}

function Get-TopLevelRelativePaths {
    param(
        [Parameter(Mandatory)][string[]]$Patterns,
        [switch]$FilesOnly,
        [switch]$DirectoriesOnly
    )

    foreach ($item in Get-ChildItem -LiteralPath $root -Force) {
        if ($FilesOnly -and $item.PSIsContainer) { continue }
        if ($DirectoriesOnly -and -not $item.PSIsContainer) { continue }
        if ($Patterns | Where-Object { $item.Name -like $_ }) {
            $item.Name
        }
    }
}

function Remove-VerifiedTarget {
    param([Parameter(Mandatory)][string]$LiteralPath)

    $item = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) { return }
    if (-not $item.PSIsContainer) {
        [System.IO.File]::SetAttributes($LiteralPath, [System.IO.FileAttributes]::Normal)
        [System.IO.File]::Delete($LiteralPath)
        return
    }

    try {
        [System.IO.Directory]::Delete($LiteralPath, $true)
    } catch {
        # Extracted toolchains and nested Git repositories can contain read-only
        # files and paths beyond legacy MAX_PATH. The path has already passed
        # Resolve-WorkspaceTarget, so delete its contents bottom-up using the
        # extended path syntax before removing the verified root.
        $extendedPath = if ($LiteralPath.StartsWith("\\")) { $LiteralPath } else { "\\?\$LiteralPath" }
        foreach ($file in [System.IO.Directory]::EnumerateFiles($extendedPath, "*", [System.IO.SearchOption]::AllDirectories)) {
            try {
                [System.IO.File]::SetAttributes($file, [System.IO.FileAttributes]::Normal)
                [System.IO.File]::Delete($file)
            } catch {
                if ([System.IO.File]::Exists($file)) { throw }
            }
        }
        $directories = @([System.IO.Directory]::EnumerateDirectories($extendedPath, "*", [System.IO.SearchOption]::AllDirectories)) |
            Sort-Object Length -Descending
        foreach ($directory in $directories) {
            try {
                [System.IO.File]::SetAttributes($directory, [System.IO.FileAttributes]::Directory)
                [System.IO.Directory]::Delete($directory, $false)
            } catch {
                if ([System.IO.Directory]::Exists($directory)) { throw }
            }
        }
        [System.IO.File]::SetAttributes($extendedPath, [System.IO.FileAttributes]::Directory)
        [System.IO.Directory]::Delete($extendedPath, $false)
    }
}

$cacheTargets = @(
    ".pytest_cache",
    ".playwright-cli",
    "output",
    "__pycache__",
    "apps\__pycache__",
    "apps\api\__pycache__",
    "apps\desktop_launcher\__pycache__",
    "mortal\__pycache__",
    "mortal_app\__pycache__",
    "simulator\__pycache__",
    "tests\__pycache__",
    "tests\api\__pycache__",
    "tests\statistics\__pycache__"
)

$buildTargets = @(
    "build",
    "target",
    "apps\web\node_modules",
    "apps\web\dist",
    "apps\web\tsconfig.tsbuildinfo",
    "exe-wrapper"
)
$buildTargets += Get-TopLevelRelativePaths -Patterns @("*.obj", "*.lib", "*.exp") -FilesOnly

$packageTargets = @(
    ".tmp-extension-regression",
    ".tmp-package-smoke",
    ".tmp-package-smoke2",
    ".tmp-release-smoke",
    ".tmp-release-smoke-final",
    ".tmp-ui-data",
    "dist-package-test",
    "dist-package-test2",
    "dist-score-fix"
)
$packageTargets += Get-TopLevelRelativePaths -Patterns @(".tmp-*")
$packageTargets += Get-TopLevelRelativePaths -Patterns @("smoke-extract-*", "release-final-lite-*") -DirectoriesOnly

if ($RemovePortable) {
    $packageTargets += Get-TopLevelRelativePaths -Patterns @("dist", "dist-*") -DirectoriesOnly
}
if ($RemoveRelease) {
    $packageTargets += Get-TopLevelRelativePaths -Patterns @("release", "release-*") -DirectoriesOnly
} elseif ($PruneRelease) {
    $checksumPath = Join-Path $root "release\SHA256SUMS.txt"
    if (-not (Test-Path -LiteralPath $checksumPath)) {
        throw "Cannot prune release without release\SHA256SUMS.txt"
    }
    $keepNames = @("SHA256SUMS.txt")
    foreach ($line in Get-Content -LiteralPath $checksumPath -Encoding UTF8) {
        if ($line -match "^[0-9A-Fa-f]{64}\s+(.+)$") {
            $keepNames += $Matches[1].Trim()
        }
    }
    if ($keepNames.Count -lt 2) {
        throw "No release assets were found in SHA256SUMS.txt"
    }
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $root "release") -Force -File) {
        if ($file.Name -notin $keepNames) {
            $packageTargets += "release\$($file.Name)"
        }
    }
}

$relativeTargets = switch ($Mode) {
    "Cache" { $cacheTargets }
    "Build" { $buildTargets }
    "Package" { $packageTargets }
    "All" { $cacheTargets + $buildTargets + $packageTargets }
}

$targets = foreach ($relative in $relativeTargets | Select-Object -Unique) {
    $absolute = Resolve-WorkspaceTarget $relative
    if (Test-Path -LiteralPath $absolute) {
        [pscustomobject]@{
            Relative = $relative
            Absolute = $absolute
            Bytes = Get-PathBytes $absolute
        }
    }
}

$totalMeasure = $targets | Measure-Object Bytes -Sum
$totalBytes = if ($null -eq $totalMeasure.Sum) { 0L } else { [long]$totalMeasure.Sum }
$action = if ($Apply) { "DELETE" } else { "WHATIF" }
Write-Host "$action mode=$Mode root=$root"
$targets |
    Sort-Object Bytes -Descending |
    Select-Object Relative, Absolute, @{Name = "GiB"; Expression = { [math]::Round($_.Bytes / 1GB, 3) } } |
    Format-Table -AutoSize
Write-Host ("Total: {0:N3} GiB" -f ($totalBytes / 1GB))

if (-not $Apply) {
    Write-Host "Dry run only. Re-run with -Apply after reviewing every path."
    exit 0
}

foreach ($target in $targets) {
    $verified = Resolve-WorkspaceTarget $target.Relative
    if ($verified -ne $target.Absolute) {
        throw "Target changed during cleanup: $($target.Relative)"
    }
    Remove-VerifiedTarget $verified
    Write-Host "Deleted $verified"
}

Write-Host ("Cleanup complete. Reclaimed approximately {0:N3} GiB." -f ($totalBytes / 1GB))
