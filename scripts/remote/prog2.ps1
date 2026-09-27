Write-Output ("now=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count + " cpu=" + [math]::Round((Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue,1))
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/pool_db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\pool_db_out.txt"
Get-Content C:\arena\pool_db_out.txt
Write-Output "--- recent ---"
Get-Content C:\arena\pool.log -ErrorAction SilentlyContinue | Select-String "s/半庄" | Select-Object -Last 4 | ForEach-Object { $_.Line }
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "-X","utf8","C:/arena/rate_pool.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\rate_out.txt"
Write-Output "--- rate_pool ---"
Get-Content C:\arena\rate_out.txt -Tail 20
