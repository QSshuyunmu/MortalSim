Write-Output ("now=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Get-Content "C:\arena\v3_exit.txt" -Tail 2
Write-Output "--- 最近完成批次 ---"
Get-Content "C:\arena\v3_stdout.log" -ErrorAction SilentlyContinue | Select-String "s/" | Select-Object -Last 8 | ForEach-Object { $_.Line }
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count + " cpu=" + [math]::Round((Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue,1))
