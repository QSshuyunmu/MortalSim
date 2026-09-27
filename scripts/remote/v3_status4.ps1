Write-Output "--- completed batches (tail 10) ---"
Get-Content "C:\arena\v3_stdout.log" -ErrorAction SilentlyContinue | Select-String "1v3" | Select-Object -Last 10 | ForEach-Object { $_.Line }
Write-Output "--- procs / CPU ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
(Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue
Write-Output "--- DB ---"
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow
