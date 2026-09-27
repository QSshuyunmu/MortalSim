Write-Output ("now=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/pool_db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\pool_db_out.txt"
Get-Content C:\arena\pool_db_out.txt
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count)
Get-Content C:\arena\pool.log -ErrorAction SilentlyContinue | Select-String "s/半庄|16 半庄|block" | Select-Object -Last 4 | ForEach-Object { $_.Line }
