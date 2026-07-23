param(
    [Parameter(Mandatory)]
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$destinationPath = [IO.Path]::GetFullPath($Destination)

if (Test-Path $destinationPath) {
    $existing = Get-ChildItem -LiteralPath $destinationPath -Force
    if ($existing.Count -gt 0) {
        throw "Destination must be empty: $destinationPath"
    }
} else {
    New-Item -ItemType Directory -Path $destinationPath | Out-Null
}

$directories = @('Akagi', 'apps', 'docs', 'libriichi', 'models', 'mortal', 'mortal_app', 'packaging', 'tests', '.github')
$rootFiles = @(
    '.gitattributes', '.gitignore', 'Cargo.lock', 'Cargo.toml', 'CONTRIBUTING.md', 'LICENSE',
    'MODEL_LICENSE.md', 'NOTICE', 'pyproject.toml', 'README.md',
    'requirements-app.txt', 'requirements-cuda.txt', 'requirements-lock.txt',
    'run_mortalsim.py', 'SECURITY.md', 'start_mortalsim.bat', 'THIRD_PARTY_LICENSES.md'
)

foreach ($directory in $directories) {
    $source = Join-Path $root $directory
    if (-not (Test-Path $source)) { continue }
    $target = Join-Path $destinationPath $directory
    Get-ChildItem -LiteralPath $source -Recurse -Force | ForEach-Object {
        $relative = $_.FullName.Substring($source.Length).TrimStart('\', '/')
        if ($relative -match '(^|\\)(target|node_modules|dist|build|release|__pycache__)(\\|$)' -or $_.Name -match '\.(pth|onnx|dll|pyd|exe|zip|log)$') {
            return
        }
        if (
            ($directory -eq 'docs' -and $relative -match '^(src|css)(\\|$)|^(book\.toml|\.gitignore)$') -or
            ($directory -eq 'libriichi' -and $relative -eq 'test_write.txt')
        ) {
            return
        }
        $output = Join-Path $target $relative
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Path $output -Force | Out-Null
        } else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $output -Force
        }
    }
}

foreach ($file in $rootFiles) {
    $source = Join-Path $root $file
    if (Test-Path $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $destinationPath $file) -Force
    }
}

Push-Location $destinationPath
try {
    git init -b main | Out-Null
    git add --all
    $trackedLarge = git ls-files | ForEach-Object {
        $item = Get-Item -LiteralPath $_
        if ($item.Length -gt 100MB) { $_ }
    }
    if ($trackedLarge) {
        throw "Public export still contains files larger than 100 MiB: $($trackedLarge -join ', ')"
    }
    $forbiddenTracked = git ls-files | Where-Object { $_ -match '\.(pth|onnx|dll|pyd|exe|zip|log|pyc)$' }
    if ($forbiddenTracked) {
        throw "Public export contains forbidden generated or model files: $($forbiddenTracked -join ', ')"
    }
    $personalPaths = @(git grep -n -I -E '[A-Za-z]:\\(Users|tenhoulib)\\' -- . 2>$null)
    if ($personalPaths) {
        throw "Public export contains absolute personal paths: $($personalPaths -join '; ')"
    }
    $secretPatterns = @(git grep -n -I -E '(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,})' -- . 2>$null)
    if ($secretPatterns) {
        throw "Public export contains a token-like secret: $($secretPatterns -join '; ')"
    }
    Write-Host "Public repository staging area is ready: $destinationPath"
    Write-Host 'Review git status, configure a public commit identity, then create the initial commit.'
} finally {
    Pop-Location
}
