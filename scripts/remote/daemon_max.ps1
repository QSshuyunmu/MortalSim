$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
Set-Location 'C:\arena'
while ($true) {
    Add-Content 'C:\arena\pool_exit.txt' -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' launch(max)')
    Start-Process -FilePath $py -ArgumentList 'C:\arena\pool_arena.py','--batch-seeds','4','--concurrency','9','--threads','2','--start-block','3','--min-concurrency','5','--max-concurrency','14' -WorkingDirectory 'C:\arena' -RedirectStandardOutput 'C:\arena\pool_stdout.log' -RedirectStandardError 'C:\arena\pool_stderr.log' -Wait -WindowStyle Hidden
    Add-Content 'C:\arena\pool_exit.txt' -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' exited, respawn in 15s')
    Start-Sleep -Seconds 15
}
