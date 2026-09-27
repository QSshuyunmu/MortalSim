$ErrorActionPreference = 'Continue'
$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
Set-Location 'C:\arena'
while ($true) {
    $proc = Get-Process python -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Output "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [Guardian] restart V3 (batch=4, conc=3, thr=4)"
        Start-Process -FilePath $py -ArgumentList 'C:\arena\arena_coordinator_v3.py','--mode','1v3','--batch-seeds','4','--concurrency','3','--threads','4' -WorkingDirectory 'C:\arena' -WindowStyle Hidden
    }
    Start-Sleep -Seconds 30
}
