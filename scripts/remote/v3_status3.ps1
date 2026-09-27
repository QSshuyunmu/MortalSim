Write-Output "--- exit log ---"
Get-Content "C:\arena\v3_exit.txt" -ErrorAction SilentlyContinue -Tail 3
Write-Output "--- completed batches ---"
Get-Content "C:\arena\v3_stdout.log" -ErrorAction SilentlyContinue | Select-String "han" | Select-Object -Last 8 | ForEach-Object { $_.Line }
Write-Output "--- procs / CPU ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
(Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue
Write-Output "--- DB ---"
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow
