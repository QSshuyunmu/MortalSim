$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
$args = @('C:\arena\arena_coordinator_v3.py','--mode','1v3','--batch-seeds','4','--concurrency','3','--threads','4')
Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory 'C:\arena' -RedirectStandardOutput 'C:\arena\v3_stdout.log' -RedirectStandardError 'C:\arena\v3_stderr.log' -WindowStyle Hidden
Start-Sleep -Seconds 20
Write-Output "--- stdout ---"
Get-Content 'C:\arena\v3_stdout.log' -ErrorAction SilentlyContinue -Tail 30
Write-Output "--- stderr ---"
Get-Content 'C:\arena\v3_stderr.log' -ErrorAction SilentlyContinue -Tail 30
Write-Output "--- procs ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
