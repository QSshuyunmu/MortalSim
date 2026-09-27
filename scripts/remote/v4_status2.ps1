Write-Output ("now=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Output "--- V4 完成批次（最近 8 条）---"
Get-Content "C:\arena\v4_stdout.log" -ErrorAction SilentlyContinue | Select-String "s/" | Select-Object -Last 8 | ForEach-Object { $_.Line }
Write-Output "--- procs / CPU ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
(Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue
Write-Output "--- DB ---"
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\db_out.txt"
Get-Content "C:\arena\db_out.txt"
