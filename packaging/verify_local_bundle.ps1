param(
    [Parameter(Mandatory)]
    [string]$Bundle,
    [Parameter(Mandatory)]
    [string]$ExpectedModelSha256,
    [int]$Port = 50931
)

$ErrorActionPreference = "Stop"
$bundlePath = [System.IO.Path]::GetFullPath($Bundle)
$executable = Join-Path $bundlePath "MortalSim.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "MortalSim.exe not found in $bundlePath"
}

$env:MORTALSIM_DATA_DIR = Join-Path $bundlePath "data"
$env:LOCALAPPDATA = Join-Path $bundlePath "localapp"
$env:MORTALSIM_ENGINE = "lite"
$env:MORTALSIM_NO_BROWSER = "1"
$env:MORTALSIM_PORT = "$Port"
$process = Start-Process -FilePath $executable -WindowStyle Hidden -PassThru
try {
    $deadline = (Get-Date).AddSeconds(45)
    do {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            break
        } catch {
            if ((Get-Date) -ge $deadline) { throw }
            Start-Sleep -Milliseconds 250
        }
    } while ($true)

    $models = @(Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/models")
    if ($models.Count -ne 1) {
        throw "Expected exactly one local model, found $($models.Count)."
    }
    if ($models[0].sha256 -ne $ExpectedModelSha256.ToLowerInvariant()) {
        throw "Unexpected local model hash: $($models[0].sha256)"
    }

    $payload = @{
        hand = "4567m3477p134066s"
        dora = "9s"
        discards = @(@{ tile = "1s"; riichi = $false })
        runs = 1
        seed = 42
        round = "E1"
        honba = 0
        kyotaku = 0
        scores = @{ self = 25000; shimocha = 25000; toimen = 25000 }
        batch_size = 1000
        model_id = $models[0].id
        rayon_threads = 20
        engine = "lite"
        decision_contract = "stable_advantage_v2"
        strict_comparison = $true
    } | ConvertTo-Json -Depth 6
    $created = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/runs" -Method Post -ContentType "application/json" -Body $payload
    $deadline = (Get-Date).AddMinutes(3)
    do {
        $run = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/runs/$($created.run_id)" -TimeoutSec 5
        if ($run.status -in @("completed", "failed", "cancelled", "interrupted")) { break }
        if ((Get-Date) -ge $deadline) { throw "Local bundle smoke timed out." }
        Start-Sleep -Milliseconds 500
    } while ($true)
    if ($run.status -ne "completed") {
        throw "Local bundle smoke failed: $($run.status) $($run.error)"
    }

    $result = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/runs/$($created.run_id)/result"
    if ($result.schema_version -ne 3 -or $result.metrics_version -ne 2) {
        throw "Unexpected result schema: $($result.schema_version)/$($result.metrics_version)"
    }
    if ($result.candidates[0].errors -ne 0) {
        throw "Local bundle smoke returned errors."
    }
    [pscustomobject]@{
        Health = $health.status
        Version = $health.version
        ModelId = $models[0].id
        ModelReady = $models[0].ready
        RunStatus = $run.status
        SchemaVersion = $result.schema_version
        MetricsVersion = $result.metrics_version
        DecisionContract = $result.decision_contract
        Games = $result.candidates[0].games
        Errors = $result.candidates[0].errors
    } | Format-List
} finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
}
