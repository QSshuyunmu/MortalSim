Write-Output ("now=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count + " cpu=" + [math]::Round((Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue,1))
Write-Output "--- DB ---"
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/pool_db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\pool_db_out.txt"
Get-Content C:\arena\pool_db_out.txt
Write-Output "--- 最近完成 ---"
Get-Content C:\arena\pool.log -ErrorAction SilentlyContinue | Select-String "s/半庄" | Select-Object -Last 4 | ForEach-Object { $_.Line }
Write-Output "--- 权威顺位报告 ---"
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "-X","utf8","C:/arena/rate_pool.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\rate_out.txt"
Get-Content C:\arena\rate_out.txt -Tail 22
