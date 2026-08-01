param(
    [Parameter(Mandatory)]
    [string]$GraphDirectory,
    [Parameter(Mandatory)]
    [string]$OutputDirectory,
    [string]$CudaRoot = $env:CUDA_PATH,
    [string]$AotiCudaShim,
    [string]$BuildId
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$graph = [IO.Path]::GetFullPath($GraphDirectory)
$output = [IO.Path]::GetFullPath($OutputDirectory)

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    throw 'cl.exe is unavailable. Run this script from an x64 Native Tools PowerShell for Visual Studio.'
}
if ([string]::IsNullOrWhiteSpace($CudaRoot)) {
    throw 'CUDA_PATH is unset. Pass -CudaRoot pointing to the pinned CUDA Toolkit used for the graph build.'
}
$cuda = [IO.Path]::GetFullPath($CudaRoot)
$model = Join-Path $graph 'model.dll'
$graphManifest = Join-Path $graph 'graph_manifest.json'
foreach ($path in @($model, $graphManifest, (Join-Path $cuda 'include\cuda_runtime_api.h'), (Join-Path $cuda 'lib\x64\cudart.lib'))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required build input is missing: $path" }
}

if ([string]::IsNullOrWhiteSpace($AotiCudaShim)) {
    $python = if ($env:PYO3_PYTHON) { $env:PYO3_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
    $candidate = & $python -c "from importlib import resources; print(resources.files('executorch').joinpath('data/lib/aoti_cuda_shims.dll'))"
    if ($LASTEXITCODE -ne 0) { throw 'Unable to locate the ExecuTorch CUDA shim.' }
    $AotiCudaShim = $candidate.Trim()
}
$shim = [IO.Path]::GetFullPath($AotiCudaShim)
if (-not (Test-Path -LiteralPath $shim)) { throw "AOTI CUDA shim is missing: $shim" }

$cudartCandidates = @(
    (Join-Path $cuda 'bin\cudart64_12.dll'),
    (Join-Path $cuda 'bin\x64\cudart64_12.dll')
)
$cudart = $cudartCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $cudart) { throw "cudart64_12.dll was not found under $cuda" }

New-Item -ItemType Directory -Force $output | Out-Null
$runtime = Join-Path $output 'mortal_lite_runtime.dll'
& cl.exe /nologo /LD /O2 /EHsc /std:c++17 `
    "/I$(Join-Path $cuda 'include')" `
    (Join-Path $root 'tools\lite_runtime\mortal_lite_runtime.cpp') `
    "/Fe:$runtime" `
    /link "/LIBPATH:$(Join-Path $cuda 'lib\x64')" cudart.lib
if ($LASTEXITCODE -ne 0) { throw "MSVC failed to build the Lite runtime (exit $LASTEXITCODE)." }

Copy-Item -LiteralPath $model -Destination (Join-Path $output 'model.dll') -Force
Copy-Item -LiteralPath $shim -Destination (Join-Path $output 'aoti_cuda_shims.dll') -Force
Copy-Item -LiteralPath $cudart -Destination (Join-Path $output 'cudart64_12.dll') -Force

$python = if ($env:PYO3_PYTHON) { $env:PYO3_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
$arguments = @(
    (Join-Path $root 'tools\build_lite_runtime_manifest.py'),
    $output,
    '--graph-manifest',
    $graphManifest
)
if ($BuildId) { $arguments += @('--build-id', $BuildId) }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Runtime manifest generation failed.' }

Write-Host "Formal Lite runtime staged at $output"
