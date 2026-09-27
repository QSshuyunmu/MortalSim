$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
Start-Process -FilePath $py -ArgumentList 'C:\arena\arena_coordinator_v3.py','--mode','1v3','--batch-seeds','4','--concurrency','3','--threads','4' -WorkingDirectory 'C:\arena' -WindowStyle Hidden
Write-Output "v3 started"
