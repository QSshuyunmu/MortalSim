Write-Output ("now=" + (Get-Date -Format "HH:mm:ss"))
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count)
Write-Output "--- tasks done ---"
Get-Content C:\arena\pool.log -ErrorAction SilentlyContinue | Select-String "hanchans" | Select-Object -Last 5 | ForEach-Object { $_.Line }
Write-Output "--- DB ---"
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/pool_db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\pool_db_out.txt"
Get-Content C:\arena\pool_db_out.txt
Write-Output "--- pool_leaderboard ---"
Get-Content C:\arena\pool_leaderboard.md -ErrorAction SilentlyContinue -Tail 12
